"""One forward-paper TICK — idempotent, catch-up safe, append-only.

  1. sync CLOSED 1h candles + funding (public endpoints);
  2. register every registry candidate not yet known (its forward history starts at registration);
  3. for every registered candidate, append one observation per newly CLOSED bar of its timeframe
     whose OPEN is after registration — never a bar that closed before the candidate existed, and
     never a bar already observed (a missed interval is caught up and flagged `late`);
  4. at most daily, re-run the backtest and re-derive lifecycle stages (append-only events);
  5. write data/trading_research/status.json for the Director report and agent_health.

Nothing here can place an order: there is no exchange client, no key, no execution import.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

from . import backtest as bt
from . import evidence as ev
from . import lifecycle as lc
from . import market_data as md
from . import ranking as rk
from .execution import EXEC_MODELS, State, funding_in_bar, step
from .metrics import evaluate
from .strategies import ASSETS, by_id, registry

REPO = Path(__file__).resolve().parents[2]
BACKTEST_EVERY_MS = 24 * 3_600_000


def data_dir() -> Path:
    """Engine state dir. Honours the fleet sandbox (SPA_DATA_DIR via live_paths) so the pre-deploy
    gate's sandboxed run never touches the live evidence (found 2026-09-30: it did, before this)."""
    if os.environ.get("SPA_TRADING_DATA_DIR"):
        return Path(os.environ["SPA_TRADING_DATA_DIR"])
    from spa_core.utils.live_paths import live_data_dir
    return live_data_dir(REPO) / "trading_research"


def _release() -> Optional[str]:
    try:
        d = json.loads((REPO / "data" / "code_sync_status.json").read_text())
        return (d.get("origin_main") or "")[:12] or None
    except (OSError, ValueError):
        return None


def _data_ref(bars, i: int, tf: str) -> str:
    w = bars[max(0, i - 299):i + 1]
    h = hashlib.sha256("".join(f"{b.open_time},{b.open},{b.high},{b.low},{b.close};" for b in w).encode())
    return f"{md.SOURCE}:{tf}:n={i + 1}:last300={h.hexdigest()[:16]}"


def _action(before: int, target: int) -> str:
    if before == target:
        return "HOLD"
    return {(0, 1): "BUY", (1, 0): "SELL", (0, -1): "SHORT", (-1, 0): "COVER"}.get((before, target), "FLIP")


FUNDING_PERIOD_MS = 8 * 3_600_000   # Binance BTCUSDT perpetual funds at 00:00 / 08:00 / 16:00 UTC


def funding_covered(fts, close_ms: int) -> bool:
    """True when the funding history reaches the last scheduled funding time at or before `close_ms`.
    A perp observation is never frozen WITHOUT funding that simply had not been synced yet."""
    due = close_ms - (close_ms % FUNDING_PERIOD_MS)
    return bool(fts) and fts[-1] >= due


def advance_candidate(conn, cand, bars, targets, *, registered_at_ms: int, now_ms: int, funding, fts,
                      code_version: str, release: Optional[str]) -> int:
    """Append observations for every new closed bar of one candidate. Returns how many."""
    model = EXEC_MODELS[cand.exec_model]
    tf_ms = md.TF_MS[cand.timeframe]
    last = ev.last_observation(conn, cand.id)
    if last:
        s = json.loads(last["book_state"])
        st = State(equity=last["equity"], position=last["position_held"], qty=s.get("qty", 0.0),
                   base=s.get("base", last["equity"]), ref=s.get("ref"), entry_eq=s.get("entry_eq"),
                   liq=s.get("liq"))
        pending, after = last["target"], last["bar_open_time"]
    else:
        st, pending, after = State(), 0, None           # first forward bar starts FLAT
    assumptions = json.dumps({"exec_model": model.name, "exec_model_version": model.version,
                              "fee_bps": model.fee_bps, "slippage_bps": model.slippage_bps,
                              "leverage": model.leverage, "funding": model.funding,
                              "timing": "target on bar close → fill at next bar open"}, sort_keys=True)
    n = 0
    for i in range(1, len(bars)):
        b = bars[i]
        if b.open_time < registered_at_ms or (after is not None and b.open_time <= after):
            continue
        if model.funding and not funding_covered(fts, b.open_time + tf_ms):
            break                                  # wait: the next tick appends it with its funding
        gap = 0 if after is None else max(0, (b.open_time - after) // tf_ms - 1)
        before = st.position
        e = step(st, b, bars[i - 1].close, pending, model,
                 funding_rates=funding_in_bar(funding, fts, b.open_time, tf_ms) if model.funding else ())
        target = targets[i]
        if not model.allow_short and target < 0:
            target = 0
        close_ms = b.open_time + tf_ms
        obs = {"candidate_id": cand.id, "asset": cand.asset, "timeframe": cand.timeframe,
               "bar_open_time": b.open_time, "bar_close_time": close_ms, "signal_ts_ms": now_ms,
               "late": int(now_ms - close_ms > max(2 * 3_600_000, tf_ms)), "gap_bars": gap,
               "bar_open": b.open, "bar_close": b.close, "position_before": before,
               "fill_price": e["fill_price"], "fill_cost": e["cost"], "funding": e["funding"],
               "position_held": st.position, "equity": st.equity, "target": target,
               "action": _action(st.position, target),
               "closed_trade": json.dumps(e["trade"], sort_keys=True) if e["trade"] else None,
               "book_state": json.dumps({"qty": st.qty, "base": st.base, "ref": st.ref,
                                         "entry_eq": st.entry_eq, "liq": st.liq}, sort_keys=True),
               "assumptions": assumptions, "data_ref": _data_ref(bars, i, cand.timeframe),
               "code_version": code_version, "release": release}
        if ev.append_observation(conn, obs):
            n += 1
        pending, after = target, b.open_time
    return n


def forward_metrics(conn, cand_id: str, tf: str) -> Dict:
    rows = list(conn.execute("SELECT equity, position_held, closed_trade, bar_open_time FROM observations "
                             "WHERE candidate_id=? ORDER BY bar_open_time", (cand_id,)))
    if not rows:
        return {"bars": 0, "measured": False}
    eq = [1.0] + [r[0] for r in rows]
    pos = [0] + [r[1] for r in rows]
    trades = [json.loads(r[2]) for r in rows if r[2]]
    m = evaluate(eq, pos, trades, tf)
    m["days"] = round((rows[-1][3] - rows[0][3]) / 86_400_000, 2)
    return m


def _qualification_snapshot(r: Optional[Dict]) -> Dict:
    """IS/OOS/OOS@3x-costs Sharpe + full-history max drawdown at the instant a candidate is
    qualified (ADR-590 fix B). Stored once, inside the append-only lifecycle event for
    BACKTEST_QUALIFIED — the daily backtest refresh keeps recomputing these numbers, but this
    snapshot is never overwritten, so a later drift is visible by DIFFERENCE, not by memory."""
    r = r or {}
    return {
        "is_sharpe": (r.get("in_sample") or {}).get("sharpe"),
        "oos_sharpe": (r.get("out_of_sample") or {}).get("sharpe"),
        "oos_sharpe_3x_costs": ((r.get("cost_sensitivity") or {}).get("3x") or {}).get("oos_sharpe"),
        "full_max_drawdown": (r.get("full") or {}).get("max_drawdown"),
    }


def _derive_stages(conn, bt_result: Dict, quals: List[Dict], now_ms: int) -> int:
    cur = ev.current_stages(conn)
    by_id_res = {r["id"]: r for r in bt_result["results"]}
    oos = {r["id"]: r["out_of_sample"].get("sharpe") for r in bt_result["results"]}   # slice_metrics: always a dict
    tfs = {r["id"]: r["definition"]["timeframe"] for r in bt_result["results"]}
    n = 0

    def move(cid, to, reason, evidence):
        nonlocal n
        frm = cur.get(cid)
        if frm == to:
            return                                           # already there: the first qualification's
                                                               # evidence stays frozen, nothing is rewritten
        lc.check(frm, to)                                   # raises on anything not automatic
        evidence = {**evidence, "admission_policy_version": lc.ADMISSION_POLICY_VERSION,
                    "admission_threshold_fingerprint": lc.admission_threshold_fingerprint()}   # ADR-640
        ev.append_event(conn, cid, frm, to, reason, evidence, actor="trading_research", now_ms=now_ms)
        cur[cid] = to
        n += 1

    for q in quals:
        cid = q["id"]
        if cur.get(cid) is None:
            move(cid, "DISCOVERED", "registered in the candidate registry", {})
        if cur.get(cid) == "DISCOVERED":
            move(cid, "BACKTESTING", "backtest run", {"code_version": bt_result["manifest"]["code_version"]})
        stage = cur.get(cid)
        if q["qualified"]:
            if stage in ("BACKTESTING", "REJECTED"):
                move(cid, "BACKTEST_QUALIFIED", "all qualification criteria met",
                     {"score": q["score"], **_qualification_snapshot(by_id_res.get(cid))})
            if cur.get(cid) == "BACKTEST_QUALIFIED":
                move(cid, "FORWARD_PAPER", "qualified; forward evidence accumulating since registration", {})
            if cur.get(cid) == "FORWARD_PAPER":
                fm = forward_metrics(conn, cid, tfs[cid])
                R = lc.ROBUST_RULES
                if (fm.get("days", 0) >= R["min_days"] and fm.get("trades", 0) >= R["min_trades"]
                        and (fm.get("sharpe") or -9) >= R["min_sharpe"] and oos.get(cid)
                        and (fm.get("sharpe") or 0) >= oos[cid] * (1 - R["max_degradation"])):
                    move(cid, "ROBUST", "forward evidence consistent with out-of-sample", {"forward": fm})
        elif stage in ("BACKTESTING", "BACKTEST_QUALIFIED", "FORWARD_PAPER", "ROBUST"):
            move(cid, "REJECTED", "failed: " + ",".join(q["rejections"]), {"rejections": q["rejections"]})
    return n


def tick(*, now_ms: Optional[int] = None, http=md._http_json, do_backtest: Optional[bool] = None) -> Dict:
    """One tick under an exclusive lock: two overlapping runs (launchd + manual) could otherwise both
    extend the same hash chain from the same predecessor. A busy lock is a clean, logged skip."""
    import fcntl
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "tick.lock", "w") as lk:
        try:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # a third outcome, not a success: this run measured nothing (the other tick will)
            return {"ok": None, "skipped": "another tick holds the lock", "new_bars": None,
                    "new_observations": None}
        return _tick(now_ms=now_ms, http=http, do_backtest=do_backtest)


def _tick(*, now_ms: Optional[int] = None, http=md._http_json, do_backtest: Optional[bool] = None) -> Dict:
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    started = now_ms
    d = data_dir()
    mconn = md.connect(d / "market.db")
    econn = ev.connect(d / "evidence.db")
    code = bt.code_version()
    rel = _release()
    detail: Dict = {}
    ok, new_bars, new_obs = True, 0, 0
    try:
        for asset, sym in ASSETS.items():
            s = md.sync_1h(mconn, sym, now_ms=now_ms, http=http)
            new_bars += s["stored"]
            md.sync_funding(mconn, sym, now_ms=now_ms, http=http)
        cands = registry()
        for c in cands:
            if ev.register(econn, c.id, c.def_hash, c.definition(), now_ms=now_ms, code_version=code):
                detail.setdefault("registered", 0)
                detail["registered"] += 1
        econn.commit()
        known = ev.registered(econn)
        reg = by_id()
        series, funding_by = {}, {}
        for asset, sym in ASSETS.items():
            b1h = md.load_1h(mconn, sym)
            for tf in {c.timeframe for c in cands}:
                series[(asset, tf)] = md.aggregate(b1h, tf)
            f = md.funding_series(mconn, sym)
            funding_by[asset] = (f, [x[0] for x in f])
        for cid, info in known.items():
            c = reg.get(cid)
            if c is None:
                continue                                   # a retired version: its history stays, frozen
            bars = series[(c.asset, c.timeframe)]
            tgt = c.signal(bars)
            funding, fts = funding_by[c.asset]
            new_obs += advance_candidate(econn, c, bars, tgt, registered_at_ms=info["registered_at_ms"],
                                         now_ms=now_ms, funding=funding, fts=fts, code_version=code,
                                         release=rel)
        econn.commit()
        bt_path = d / "backtest.json"
        prev = _bt_manifest(bt_path)
        need = do_backtest if do_backtest is not None else (
            prev is None or prev.get("code_version") != code
            or not isinstance(prev.get("generated_at_ms"), int)       # unknown age ⇒ refresh, never «fresh»
            or now_ms - prev["generated_at_ms"] > BACKTEST_EVERY_MS)
        if need:
            # ADR-590 fix B: OOS stops at the forward clock's start (MIN over every registered
            # candidate — they all register in the same tick today, so this is one fixed instant,
            # never pushed forward by the daily refresh). No candidate registered yet ⇒ None,
            # the old open-ended slice.
            oos_end_ms = econn.execute("SELECT MIN(registered_at_ms) FROM candidates").fetchone()[0]
            res = bt.run_all(mconn, now_ms=now_ms, oos_end_ms=oos_end_ms)
            bt.save(res, bt_path)
            bt.save_versioned(res, d)
            detail["backtest"] = "refreshed"
        res = json.loads(bt_path.read_text())
        b1h = md.load_1h(mconn, ASSETS["BTC"])
        gate_end = rk.gate_window_end(res)        # ADR-640 §P2-4: one window for gates AND benchmark
        bms = {tf: rk.benchmark(md.aggregate(b1h, tf), tf, gate_end) for tf in {c.timeframe for c in cands}}
        quals = rk.qualify(res["results"], bms)
        res.setdefault("manifest", {})["gate_window_end_ms"] = gate_end
        detail["stage_events"] = _derive_stages(econn, res, quals, now_ms)
        econn.commit()
        short = rk.shortlist(res["results"], quals)
        write_status(econn, mconn, res, quals, short, bms, now_ms=now_ms, code=code, release=rel)
    except Exception as e:  # noqa: BLE001 — recorded, surfaced, and the tick exits non-zero
        ok = False
        detail["error"] = f"{type(e).__name__}: {e}"
    finally:
        ev.record_tick(econn, started_ms=started, finished_ms=int(time.time() * 1000), new_bars=new_bars,
                       new_obs=new_obs, ok=ok, detail=detail, code_version=code)
        econn.commit()
        if not ok:
            _write_failed_status(detail, now_ms)
    return {"ok": ok, "new_bars": new_bars, "new_observations": new_obs, **detail}


def _bt_manifest(p: Path) -> Optional[Dict]:
    try:
        return json.loads(p.read_text())["manifest"]
    except (OSError, ValueError, KeyError):
        return None


def write_status(econn, mconn, res, quals, short, bms, *, now_ms, code, release) -> Dict:
    from collections import Counter
    from spa_core.utils.atomic import atomic_save
    cur_stages = ev.current_stages(econn)
    stages = Counter(cur_stages.values())
    by_id_res = {r["id"]: r for r in res["results"]}
    last_bar = {tf: t for tf, t in econn.execute(
        "SELECT timeframe, MAX(bar_close_time) FROM observations GROUP BY timeframe")}
    first = econn.execute("SELECT MIN(registered_at_ms) FROM candidates").fetchone()[0]
    ver = ev.verify(econn)
    # ADR-590 fix D8: the FORWARD set is read from lifecycle_events (current stage), never from the
    # backtest shortlist below — shortlist is the top-5 AFTER correlation de-dup and today happens
    # to coincide (5 == 5), but it is a different set by construction and will diverge once more
    # than 5 candidates qualify, or de-dup drops one that is still FORWARD_PAPER.
    fwd_ids = [cid for cid, s in cur_stages.items() if s in ("FORWARD_PAPER", "ROBUST")]
    forward_candidates = []
    for cid in fwd_ids:
        r = by_id_res.get(cid)
        if r is None:
            continue
        fm = forward_metrics(econn, cid, r["definition"]["timeframe"])
        forward_candidates.append({
            "id": cid, "stage": cur_stages.get(cid),
            "oos_sharpe": r["out_of_sample"].get("sharpe"),
            "oos_max_drawdown": r["out_of_sample"].get("max_drawdown"),
            # ADR-590 fix D7: the FULL-history drawdown is the binding gate (q_drawdown); the
            # Director report used to print only the shallower OOS number as "просадка" — show both.
            "full_max_drawdown": r["full"].get("max_drawdown"),
            "forward_observations": ev.observation_count(econn, cid),   # fix D1: real COUNT(*), no +1 seed
            "forward_net": fm.get("net_return"),
        })
    forward_candidates.sort(key=lambda c: (c["oos_sharpe"] is None, -(c["oos_sharpe"] or 0)))
    top = []
    for s in short[:5]:
        r = by_id_res[s["id"]]
        fm = forward_metrics(econn, s["id"], r["definition"]["timeframe"])
        top.append({"id": s["id"], "score": s["score"],
                    "oos_sharpe": r["out_of_sample"].get("sharpe"),
                    "oos_max_drawdown": r["out_of_sample"].get("max_drawdown"),
                    "full_max_drawdown": r["full"].get("max_drawdown"),
                    "forward_observations": ev.observation_count(econn, s["id"]),
                    "forward_net": fm.get("net_return")})
    status = {
        "schema": "trading-research-status/1", "generated_at_ms": now_ms, "ok": True,
        "code_version": code, "release": release, "mode": "PAPER_RESEARCH_ONLY", "live_capital_usd": 0,
        "candidates": len(quals), "stages": dict(stages),
        "backtest_qualified": sum(1 for q in quals if q["qualified"]),
        "forward_paper": len(fwd_ids),
        "observations": ver["observations"], "chains": ver["chains"], "evidence_verified": ver["ok"],
        "evidence_breaks": ver["breaks"][:5],
        "forward_since_ms": first, "last_bar_close_ms": last_bar,
        "backtest_generated_at_ms": res["manifest"].get("generated_at_ms"),
        "data": {"bars_1h": res["manifest"]["bars_1h"], "gaps_1h": res["manifest"]["gaps_1h"]},
        "benchmark": {tf: {"sharpe": m.get("sharpe"), "max_drawdown": m.get("max_drawdown")} for tf, m in bms.items()},
        # what `benchmark` IS (ADR-640): buy-and-hold BTC over the window the qualification gates judge
        "benchmark_window": {"kind": "buy_and_hold_btc",
                             "end_ms": (res.get("manifest") or {}).get("gate_window_end_ms"),
                             "note": ("history up to the forward clock's start"
                                      if (res.get("manifest") or {}).get("gate_window_end_ms") is not None
                                      else "full history (backtest written before the gating slice existed)")},
        # "shortlist" = backtest top-5 after correlation de-dup (ranking/diagnostic use only).
        # "forward_candidates" = the actual FORWARD_PAPER/ROBUST set (fix D8) — readers that mean
        # "what is the engine's live forward state" must use this one, not shortlist.
        "shortlist": top,
        "forward_candidates": forward_candidates,
    }
    atomic_save(status, str(data_dir() / "status.json"))
    return status


def _write_failed_status(detail, now_ms):
    from spa_core.utils.atomic import atomic_save
    p = data_dir() / "status.json"
    try:
        prev = json.loads(p.read_text())
    except (OSError, ValueError):
        prev = {}
    prev.update({"ok": False, "failed_at_ms": now_ms, "error": detail.get("error")})
    prev.setdefault("generated_at_ms", now_ms)       # a first-ever failure must still reach the report
    atomic_save(prev, str(p))
