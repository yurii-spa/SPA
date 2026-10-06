"""trading_lab_view() — Director OS v2's read model for the "Trading Lab" card (RM-TRUTH-01 C1,
ADR-590). Pure read, no network, LLM_FORBIDDEN, stdlib only — like the rest of this package.

Every cell is ``{value, metric_type, as_of, source, state}``, ``state`` one of MEASURED /
MEASURED_ZERO / NOT_MEASURED / NOT_ENOUGH_HISTORY (invariant #17): absence of an observation is
always a distinct, visible outcome, never a fabricated zero or an empty collection that reads the
same as "nothing to report".

This module never opens ``evidence.db`` for writing: it connects with the sqlite URI
``mode=ro``, which refuses even the schema-creation DDL that ``evidence.connect()`` runs — so it
deliberately does NOT call that function, only the plain read helpers in ``evidence`` that assume
the schema already exists (``verify``, ``registered``, ``current_stages``, ``last_observation``,
``observation_count``). Nothing here can place an order; there is no exchange client, no key, no
execution import.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Dict, Optional

from . import evidence as ev

MEASURED = "MEASURED"
MEASURED_ZERO = "MEASURED_ZERO"
NOT_MEASURED = "NOT_MEASURED"
NOT_ENOUGH_HISTORY = "NOT_ENOUGH_HISTORY"

#: the same thresholds the Director report / lifecycle use for "is this report stale" and "is this
#: forward track long enough to show a windowed return" (lifecycle.ROBUST_RULES min_days).
STALE_AFTER_H = 2.0
MATURE_7D_DAYS = 7.0
MATURE_30D_DAYS = 30.0


def _cell(value, *, metric_type: str, source: str, as_of=None, state: Optional[str] = None,
          reason: Optional[str] = None) -> Dict:
    """`state=None` infers MEASURED / MEASURED_ZERO / NOT_MEASURED from `value` — pass `state`
    explicitly for NOT_ENOUGH_HISTORY, or whenever 0 is a measured count rather than an absence.

    `reason` is the inv #17 third-outcome text (Russian, human-readable: *why* there is no
    observation — "evidence.db не найден по пути …", "status.json нечитаем: …"). A cell that
    resolves to NOT_MEASURED without one is a bug in the caller, not a quiet absence — raising
    here is cheaper than letting the dashboard print a reason-less blank."""
    if state is None:
        state = NOT_MEASURED if value is None else (MEASURED_ZERO if value == 0 else MEASURED)
    if state == NOT_MEASURED and not reason:
        raise ValueError(
            f"inv #17: NOT_MEASURED cell (metric_type={metric_type!r}, source={source!r}) без reason")
    return {"value": value, "metric_type": metric_type, "as_of": as_of, "source": source,
            "state": state, "reason": reason}


def _read_json(path: Path):
    """Returns `(doc, reason)`. `reason` is a Russian string set exactly when `doc` is None, and
    it names WHICH of the three ways reading failed — missing file / unreadable JSON / not an
    object — rather than collapsing them into one undifferentiated ``None`` (inv #17)."""
    p = Path(path)
    if not p.exists():
        return None, f"{p.name} не найден по пути {p}"
    try:
        raw = p.read_text()
    except OSError as e:
        return None, f"{p.name} нечитаем ({type(e).__name__}: {e})"
    try:
        doc = json.loads(raw)
    except ValueError as e:
        return None, f"{p.name} не парсится как JSON: {e}"
    if not isinstance(doc, dict):
        return None, f"{p.name} не является JSON-объектом (dict) по пути {p}"
    return doc, None


def _ro_connect(path: Path):
    """Returns `(conn, reason)` — mirrors `_read_json`: `reason` (Russian) is set exactly when
    `conn` is None, naming "not found" vs. a real sqlite error opening read-only."""
    p = Path(path)
    if not p.exists():
        return None, f"evidence.db не найден по пути {p}"
    try:
        return sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True), None
    except sqlite3.Error as e:
        return None, f"evidence.db не открывается в режиме mode=ro ({type(e).__name__}: {e})"


def trading_lab_view(data_dir, *, now_ms: Optional[int] = None,
                     earn_defi_track: Optional[Dict] = None) -> Dict:
    """`data_dir` is the repo's own ``data/`` directory — the same canonical argument every other
    Director OS v2 read model takes (`company_truth.studio_problems`, `.studio_backups`, …).
    Resolved internally to ``data_dir/trading_research``, the engine's state directory.

    Backward-compatible: if `data_dir` itself already directly contains ``evidence.db`` (detected
    by presence, not by name — callers on the earlier contract passed the ``trading_research`` dir
    itself), it is used AS GIVEN instead of appending another ``trading_research`` beneath it. This
    was a real defect (RM-TRUTH-01 Wave 2): calling this with the repo ``data/`` dir under the OLD
    contract silently returned NOT_MEASURED for all 21 fields — no exception, no visible hint,
    because every path beneath the wrong directory simply does not exist.

    `now_ms` defaults to the wall clock, used only for staleness/maturity math — never to invent a
    value. `earn_defi_track` is an already-fetched snapshot of earn-defi's published
    ``track.json`` (this module makes no network calls itself); omit it and the
    ``related_products`` cell is honestly NOT_MEASURED rather than silently summed with the Lab."""
    data_dir = Path(data_dir)
    if not (data_dir / "evidence.db").exists():
        data_dir = data_dir / "trading_research"
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    status, status_reason = _read_json(data_dir / "status.json")
    status = status or {}
    backtest, backtest_reason = _read_json(data_dir / "backtest.json")
    backtest = backtest or {}
    manifest = backtest.get("manifest") or {}
    by_id_bt = {r["id"]: r for r in (backtest.get("results") or []) if isinstance(r, dict) and r.get("id")}

    status_src = "data/trading_research/status.json"
    ev_src = "data/trading_research/evidence.db"
    bt_src = "data/trading_research/backtest.json"
    both_src = f"{ev_src}, {status_src}"

    gen_ms = status.get("generated_at_ms")
    age_h = (now_ms - gen_ms) / 3_600_000.0 if isinstance(gen_ms, (int, float)) else None

    out: Dict[str, Dict] = {}

    # engine_health — HEALTHY / STALE / BROKEN / None(NOT_MEASURED), never inferred from presence alone.
    health_reason = None
    if age_h is None:
        health = None
        health_reason = status_reason or f"{status_src} не содержит generated_at_ms"
    elif status.get("evidence_verified") is False:
        health = "BROKEN"
    elif status.get("ok") is False or age_h > STALE_AFTER_H:
        health = "STALE"
    elif status.get("ok") is True and status.get("evidence_verified") is True:
        health = "HEALTHY"
    else:
        health = None
        health_reason = (f"{status_src} содержит ok={status.get('ok')!r}, "
                         f"evidence_verified={status.get('evidence_verified')!r} — не укладывается "
                         "ни в HEALTHY, ни в STALE, ни в BROKEN")
    out["engine_health"] = _cell(health, metric_type="OPERATIONAL",
                                 source=f"{status_src}, launchctl list com.spa.trading_research", as_of=gen_ms,
                                 reason=health_reason)

    conn, conn_reason = _ro_connect(data_dir / "evidence.db")
    if conn is None:
        for k in ("evidence_integrity", "strategies_researched", "forward_paper_active", "champions",
                  "latest_btc_signal_forward", "btc_signal_consensus_by_timeframe", "forward_start",
                  "forward_periods", "last_observation", "performance_since_forward_start",
                  "performance_7d", "performance_30d", "drawdown_forward"):
            out[k] = _cell(None, metric_type="OPERATIONAL" if k in ("evidence_integrity",) else "COUNT",
                           source=ev_src, as_of=gen_ms, reason=conn_reason)
        out["robustness_pass"] = _cell(None, metric_type="BACKTEST_QUALIFICATION", source=both_src, as_of=gen_ms,
                                       reason=conn_reason)
        fwd_ids, stages_by_id = [], {}
    else:
        try:
            v = ev.verify(conn)
            n_reg_times = conn.execute("SELECT COUNT(DISTINCT registered_at_ms) FROM candidates").fetchone()[0]
            triggers = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0]
            verified = bool(v["ok"]) and triggers == 8 and n_reg_times <= 1
            out["evidence_integrity"] = _cell("VERIFIED" if verified else "BROKEN", metric_type="OPERATIONAL",
                                              source=ev_src, as_of=gen_ms)

            registered = ev.registered(conn)
            out["strategies_researched"] = _cell(len(registered), metric_type="COUNT", source=ev_src, as_of=gen_ms)

            stages_by_id = ev.current_stages(conn)
            fwd_ids = [cid for cid, s in stages_by_id.items() if s in ("FORWARD_PAPER", "ROBUST")]
            robust_ids = [cid for cid, s in stages_by_id.items() if s == "ROBUST"]
            champ_ids = [cid for cid, s in stages_by_id.items() if s in ("CHAMPION_CANDIDATE", "SHADOW")]

            out["robustness_pass"] = _cell(
                {"backtest_qualified": status.get("backtest_qualified"), "robust": len(robust_ids)},
                metric_type="BACKTEST_QUALIFICATION", source=both_src, as_of=gen_ms)
            out["forward_paper_active"] = _cell(len(fwd_ids), metric_type="COUNT", source=ev_src, as_of=gen_ms)
            out["champions"] = _cell(len(champ_ids), metric_type="COUNT", source=ev_src, as_of=gen_ms)

            # one pass over every registered candidate's LAST observation: feeds both the
            # per-timeframe breadth (field 8, over ALL candidates incl. REJECTED) and the forward
            # signal list (field 7, forward_ids only) — the engine's own `last_observation` helper,
            # never a re-derived query.
            breadth: Dict[str, Dict[str, int]] = {}
            forward_signal = {}
            for cid in registered:
                last = ev.last_observation(conn, cid)
                if last is None:
                    continue
                tf = last["timeframe"]
                sign = "long" if last["target"] > 0 else ("short" if last["target"] < 0 else "flat")
                breadth.setdefault(tf, {"long": 0, "flat": 0, "short": 0})[sign] += 1
                if cid in fwd_ids:
                    forward_signal[cid] = {
                        "timeframe": tf, "bar_close_time": last["bar_close_time"],
                        "position_held": last["position_held"], "target": last["target"],
                        "action": last["action"],
                    }
            out["btc_signal_consensus_by_timeframe"] = _cell(
                breadth, metric_type="DIAGNOSTIC_BREADTH",
                source=ev_src, as_of=gen_ms,
                state=(NOT_MEASURED if not breadth else MEASURED),
                reason=(None if breadth else
                        "ни один из зарегистрированных кандидатов не имеет наблюдений "
                        "(last_observation вернул None для всех)"))
            fwd_empty_reason = "нет кандидатов в стадии FORWARD_PAPER или ROBUST (fwd_ids пуст)"
            out["latest_btc_signal_forward"] = _cell(
                forward_signal, metric_type="FORWARD_PAPER_SIGNAL", source=ev_src, as_of=gen_ms,
                state=(NOT_MEASURED if not fwd_ids else MEASURED),
                reason=(None if fwd_ids else fwd_empty_reason))

            forward_start, forward_periods, last_obs, perf_since, perf_7d, perf_30d, dd_fwd = (
                {}, {}, {}, {}, {}, {}, {})
            for cid in fwd_ids:
                reg_ms = (registered.get(cid) or {}).get("registered_at_ms")
                first_open, last_open = conn.execute(
                    "SELECT MIN(bar_open_time), MAX(bar_open_time) FROM observations WHERE candidate_id=?",
                    (cid,)).fetchone()
                n_obs = ev.observation_count(conn, cid)
                forward_start[cid] = {"registered_at_ms": reg_ms, "first_forward_bar_open_ms": first_open}
                forward_periods[cid] = n_obs                   # fix D1: real COUNT(*), never +1
                last = ev.last_observation(conn, cid)
                last_obs[cid] = ({"bar_close_time": last["bar_close_time"], "late": last["late"],
                                  "gap_bars": last["gap_bars"]} if last else None)

                rows = list(conn.execute(
                    "SELECT bar_close_time, equity FROM observations WHERE candidate_id=? "
                    "ORDER BY bar_open_time", (cid,)))
                if not rows:
                    perf_since[cid] = None
                    perf_7d[cid] = {"state": NOT_ENOUGH_HISTORY, "days_elapsed": 0}
                    perf_30d[cid] = {"state": NOT_ENOUGH_HISTORY, "days_elapsed": 0}
                    dd_fwd[cid] = None
                    continue
                eq_series = [1.0] + [r[1] for r in rows]
                last_eq = eq_series[-1]
                days = (rows[-1][0] - rows[0][0]) / 86_400_000.0
                closed = conn.execute(
                    "SELECT COUNT(*) FROM observations WHERE candidate_id=? AND closed_trade IS NOT NULL",
                    (cid,)).fetchone()[0]
                perf_since[cid] = {"net_return": last_eq / eq_series[0] - 1, "closed_trades": closed,
                                   "days_elapsed": round(days, 2)}

                def _windowed(window_days: float):
                    cutoff = rows[-1][0] - int(window_days * 86_400_000)
                    base = next((r[1] for r in rows if r[0] <= cutoff), None)
                    if base is None or days < window_days:
                        return {"state": NOT_ENOUGH_HISTORY, "days_elapsed": round(days, 2)}
                    return {"net_return": last_eq / base - 1, "days_elapsed": round(days, 2)}

                perf_7d[cid] = _windowed(MATURE_7D_DAYS)
                perf_30d[cid] = _windowed(MATURE_30D_DAYS)

                peak, mdd = eq_series[0], 0.0
                for v2 in eq_series:
                    peak = max(peak, v2)
                    mdd = min(mdd, v2 / peak - 1 if peak > 0 else -1.0)
                dd_fwd[cid] = mdd

            _r = None if fwd_ids else fwd_empty_reason
            out["forward_start"] = _cell(forward_start, metric_type="TIMESTAMP", source=ev_src, as_of=gen_ms,
                                         state=(NOT_MEASURED if not fwd_ids else MEASURED), reason=_r)
            out["forward_periods"] = _cell(forward_periods, metric_type="COUNT", source=ev_src, as_of=gen_ms,
                                           state=(NOT_MEASURED if not fwd_ids else MEASURED), reason=_r)
            out["last_observation"] = _cell(last_obs, metric_type="TIMESTAMP", source=ev_src, as_of=gen_ms,
                                            state=(NOT_MEASURED if not fwd_ids else MEASURED), reason=_r)
            out["performance_since_forward_start"] = _cell(
                perf_since, metric_type="REALIZED_PAPER_RETURN", source=ev_src, as_of=gen_ms,
                state=(NOT_MEASURED if not fwd_ids else MEASURED), reason=_r)
            out["performance_7d"] = _cell(perf_7d, metric_type="REALIZED_PAPER_RETURN", source=ev_src, as_of=gen_ms,
                                          state=(NOT_MEASURED if not fwd_ids else MEASURED), reason=_r)
            out["performance_30d"] = _cell(perf_30d, metric_type="REALIZED_PAPER_RETURN", source=ev_src, as_of=gen_ms,
                                           state=(NOT_MEASURED if not fwd_ids else MEASURED), reason=_r)
            out["drawdown_forward"] = _cell(dd_fwd, metric_type="FORWARD_PAPER_DRAWDOWN", source=ev_src, as_of=gen_ms,
                                            state=(NOT_MEASURED if not fwd_ids else MEASURED), reason=_r)
        finally:
            conn.close()

    out["backtests"] = _cell(
        {"count": len(backtest.get("results") or []), "generated_at_ms": manifest.get("generated_at_ms"),
         "bars_1h": manifest.get("bars_1h"), "gaps_1h": manifest.get("gaps_1h")}
        if backtest else None,
        metric_type="BACKTEST", source=bt_src, as_of=manifest.get("generated_at_ms"),
        reason=(None if backtest else (backtest_reason or f"{bt_src} пуст (нет результатов)")))

    # drawdown_backtest — FULL beside OOS for every forward candidate (fix D7): never print OOS
    # alone as "the" drawdown, since the binding gate (q_drawdown) is the full-history number.
    dd_bt = {}
    for cid in (out.get("latest_btc_signal_forward", {}).get("value") or {}):
        r = by_id_bt.get(cid) or {}
        dd_bt[cid] = {"full_max_drawdown": (r.get("full") or {}).get("max_drawdown"),
                      "oos_max_drawdown": (r.get("out_of_sample") or {}).get("max_drawdown")}
    out["drawdown_backtest"] = _cell(
        dd_bt, metric_type="BACKTEST_DRAWDOWN", source=bt_src,
        as_of=manifest.get("generated_at_ms"),
        state=(NOT_MEASURED if not dd_bt else MEASURED),
        reason=(None if dd_bt else
                (out.get("latest_btc_signal_forward", {}).get("reason") or "latest_btc_signal_forward пуст")))

    # oos_contamination_D2 — True only when the manifest carries NO freeze point at all (pre-fix
    # files); once oos_end_ms is published (fix B), OOS is frozen at forward_start by construction.
    if not manifest:
        contaminated = None
    else:
        contaminated = manifest.get("oos_end_ms") is None and manifest.get("data_to_ms") is not None
    out["oos_contamination_D2"] = _cell(
        contaminated, metric_type="METHODOLOGY_FLAG", source=bt_src,
        as_of=manifest.get("generated_at_ms"),
        reason=(None if manifest else (backtest_reason or f"{bt_src} не содержит manifest")))

    data_gaps_value = (
        {"gaps_1h": (status.get("data") or {}).get("gaps_1h"),
         "evidence_breaks": status.get("evidence_breaks")} if status else None)
    out["data_gaps"] = _cell(
        data_gaps_value, metric_type="DATA_QUALITY", source=both_src, as_of=gen_ms,
        reason=(None if status else (status_reason or f"{status_src} пуст")))

    live_cap = status.get("live_capital_usd")
    out["live_capital"] = _cell(
        live_cap, metric_type="POLICY", source=status_src, as_of=gen_ms,
        reason=(None if live_cap is not None else
                (status_reason or f"{status_src} не содержит live_capital_usd")))

    # related_products — never fetched here (no network in this package); a caller that already
    # has earn-defi's published track passes it in, otherwise this is honestly NOT_MEASURED, and
    # it is NEVER added into any Lab total (same BTC beta; ADR-590 §2).
    if earn_defi_track is None:
        out["related_products"] = _cell(
            None, metric_type="EXTERNAL_PRODUCT_REFERENCE",
            source="~/Documents/earn-defi (not read by this view)",
            reason="earn_defi_track не передан вызывающим кодом — этот модуль сам не делает сетевых запросов")
    else:
        sys_mode = earn_defi_track.get("system_mode")
        out["related_products"] = _cell(
            {k: earn_defi_track.get(k) for k in ("nav_usdt", "cum_return", "max_drawdown", "btc_weight",
                                                  "date", "system_mode")},
            metric_type="EXTERNAL_PRODUCT_REFERENCE", source="earn-defi track.json (external, caller-supplied)",
            as_of=earn_defi_track.get("date"),
            state=(NOT_MEASURED if sys_mode is None else MEASURED),
            reason=(None if sys_mode is not None else "earn-defi track.json не содержит system_mode"))

    return out
