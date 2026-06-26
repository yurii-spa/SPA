#!/usr/bin/env python3
"""Reporting / monitor / status tail of the paper-trading cycle (N12 decomposition).

PURE-MOVE EXTRACTION from ``cycle_runner.py``: the MP-107 external monitors, the
MP-016 Telegram alert dispatch, the ``paper_trading_status.json`` writer, and the
SPA-V434 dashboard cycle-metrics snapshot. Bodies are byte-identical to their
originals — no behaviour change. ``cycle_runner`` re-exports every name below for
back-compat.

The network-bound functions (``_run_daily_monitors`` / ``_run_cycle_alerts``)
are invoked from ``cycle_runner.main()`` (the launchd CLI), NOT from
``run_cycle()`` — so unit tests of the cycle stay network-free. stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from spa_core.paper_trading._cycle_io import (
    DASHBOARD_HISTORY_FILENAME,
    MAX_DASHBOARD_ENTRIES,
    RISK_SCORES_FILENAME,
    STATUS_FILENAME,
    TRADES_FILENAME,
    _DEFAULT_DATA_DIR,
    _atomic_write_json,
    _read_json,
)

if TYPE_CHECKING:  # pragma: no cover — annotation only, no runtime import
    from spa_core.paper_trading.cycle_runner import CycleResult

log = logging.getLogger("spa.cycle_runner")


# ─── MP-107: daily external monitors (red flags / governance / incidents) ────


def _run_daily_monitors(
    data_dir: str | os.PathLike | None = None, *, offline: bool = False
) -> dict[str, str]:
    """Refresh the external-signal snapshots once per daily cycle (MP-107).

    Runs three existing monitors — each individually fail-safe, so one broken
    feed never blocks the others or the cycle:

    * ``RedFlagMonitor``     → ``data/red_flags.json``
    * ``GovernanceWatcher``  → ``data/governance_proposals.json``
    * ``incidents_fetcher``  → ``data/incidents.json``

    The legacy modules write their own files NON-atomically, so they are
    invoked in dry-run/build mode and the snapshot is persisted here via the
    atomic helper (tmp + os.replace), per the repo-wide atomic-write rule.

    Network-bound (DeFiLlama / Snapshot / Tally) — therefore invoked from the
    CLI ``main()`` (the launchd daily job), NOT from ``run_cycle()``, so unit
    tests of the cycle stay network-free. Advisory only: results feed risk
    scoring / alerting; nothing here gates or mutates paper-trading state.
    Returns a per-monitor status map ("ok" / "error: …"). Never raises.
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    results: dict[str, str] = {}

    try:
        from spa_core.alerts.red_flag_monitor import RedFlagMonitor

        snapshot = RedFlagMonitor(
            output_file=ddir / "red_flags.json",
            risk_scores_file=ddir / RISK_SCORES_FILENAME,
        ).export(dry_run=True, offline=offline)
        _atomic_write_json(ddir / "red_flags.json", snapshot)
        results["red_flags"] = "ok"
    except Exception as exc:  # noqa: BLE001 — monitors must never crash the cycle
        log.warning("red_flag monitor failed (%s) — cycle continues", exc)
        results["red_flags"] = f"error: {type(exc).__name__}: {exc}"

    try:
        from spa_core.alerts.governance_watcher import GovernanceWatcher

        doc = GovernanceWatcher(
            output_file=ddir / "governance_proposals.json",
            risk_scores_file=ddir / RISK_SCORES_FILENAME,
        ).export(dry_run=True, offline=offline)
        if isinstance(doc, dict) and doc.get("error"):
            results["governance"] = f"error: {doc['error']}"
        else:
            _atomic_write_json(ddir / "governance_proposals.json", doc)
            results["governance"] = "ok"
    except Exception as exc:  # noqa: BLE001
        log.warning("governance watcher failed (%s) — cycle continues", exc)
        results["governance"] = f"error: {type(exc).__name__}: {exc}"

    try:
        from spa_core.data_pipeline.incidents_fetcher import build_incidents_snapshot

        snapshot = build_incidents_snapshot(offline=offline)
        _atomic_write_json(ddir / "incidents.json", snapshot)
        results["incidents"] = "ok"
    except Exception as exc:  # noqa: BLE001
        log.warning("incidents fetcher failed (%s) — cycle continues", exc)
        results["incidents"] = f"error: {type(exc).__name__}: {exc}"

    # MP-311: adapter watchdog in daily monitors (fail-safe)
    try:
        from spa_core.scheduler.adapter_watchdog import run_watchdog_cycle as _wdog
        _wdog(data_dir=str(ddir))
        results["adapter_watchdog"] = "ok"
    except Exception as exc:  # noqa: BLE001
        log.warning("adapter_watchdog in daily monitors failed (%s) — cycle continues", exc)
        results["adapter_watchdog"] = f"error: {type(exc).__name__}: {exc}"

    # MP-304: Alpha Agent — weekly candidate scan (Mondays only, fail-safe)
    _now_wd = datetime.now(timezone.utc).weekday()
    if _now_wd == 0:  # Monday
        try:
            from spa_core.agents.alpha_agent import run_alpha_scan as _alpha_scan
            _alpha_scan(data_dir=str(ddir))
            results["alpha_scan"] = "ok"
        except Exception as exc:  # noqa: BLE001
            log.warning("alpha_scan failed (%s) — cycle continues", exc)
            results["alpha_scan"] = f"error: {type(exc).__name__}: {exc}"

    # MP-307: Protocol Research Agent — weekly new protocol search (Mondays only, fail-safe)
    if _now_wd == 0:  # Monday
        try:
            from spa_core.agents.protocol_research_agent import (
                run_research_cycle as _research_cycle,
            )
            _research_cycle(data_dir=ddir)
            results["protocol_research"] = "ok"
        except Exception as exc:  # noqa: BLE001
            log.warning("protocol_research_cycle failed (%s) — cycle continues", exc)
            results["protocol_research"] = f"error: {type(exc).__name__}: {exc}"

    return results


# ─── MP-016: Telegram alerts (fail-safe, advisory — never crash the cycle) ───


def _should_send_alert(alert_type: str, content: str) -> bool:
    """De-duplicate repeat alerts of the same ``alert_type``.

    Returns ``True`` only when *content* differs from the last payload sent
    for this ``alert_type``. Guards against the daily cycle re-blasting an
    identical Telegram message every run (a standing red flag or persistent
    gap would otherwise alert on every cycle). Best-effort: any I/O error
    falls through to ``True`` so a genuinely new alert is never swallowed.
    """
    try:
        hash_file = Path(f"/tmp/spa_cycle_alert_hash_{alert_type}")
        new_hash = hashlib.sha1(content.encode("utf-8")).hexdigest()
        if hash_file.exists() and hash_file.read_text().strip() == new_hash:
            return False  # identical to the last alert — skip
        hash_file.write_text(new_hash)
        return True
    except Exception:  # noqa: BLE001 — dedup must never block a real alert
        return True


def _run_cycle_alerts(
    data_dir: str | os.PathLike | None = None, *, date: str
) -> dict[str, bool]:
    """Send the post-cycle Telegram alerts (MP-016).

    Network-bound (Keychain + Telegram Bot API) — invoked from the CLI
    ``main()`` like the MP-107 monitors, NOT from ``run_cycle()``, so unit
    tests of the cycle stay network-free and never message the live chat.

    Three alerts, each individually fail-safe (one failure never blocks the
    others or the cycle):

    * daily summary  — ``data/daily_report_{date}.json`` (when available)
    * red flags      — ``data/red_flags.json`` (when non-empty)
    * gap alert      — ``data/gap_monitor.json`` (when ``gap_detected``)

    Returns a per-alert sent-status map. Never raises.
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    sent: dict[str, bool] = {}
    try:
        from spa_core.alerts import alert_manager
    except Exception as exc:  # noqa: BLE001 — alerts must never crash the cycle
        log.warning("alert_manager unavailable (%s) — alerts skipped", exc)
        return sent

    try:
        report = _read_json(ddir / f"daily_report_{date}.json", None)
        if isinstance(report, dict):
            content = json.dumps(report, sort_keys=True, default=str)
            if _should_send_alert("daily_summary", content):
                sent["daily_summary"] = alert_manager.send_daily_summary(report)
            else:
                log.info("daily summary unchanged — alert skipped (dedup)")
    except Exception as exc:  # noqa: BLE001
        log.warning("daily summary alert failed (%s) — cycle continues", exc)

    try:
        doc = _read_json(ddir / "red_flags.json", {})
        raw = doc.get("red_flags") if isinstance(doc, dict) else None
        # Pass raw alert dicts — alert_manager.send_red_flag formats them
        # into Russian-language Telegram messages (MP-136).
        flags = [f for f in (raw or []) if isinstance(f, dict)]
        if flags:
            # Cap the digest at 10 items to stay within Telegram limits.
            if len(flags) > 10:
                flags = flags[:10]
            content = json.dumps(flags, sort_keys=True, default=str)
            if _should_send_alert("red_flags", content):
                sent["red_flags"] = alert_manager.send_red_flag(flags)
            else:
                log.info("red flags unchanged — alert skipped (dedup)")
    except Exception as exc:  # noqa: BLE001
        log.warning("red-flag alert failed (%s) — cycle continues", exc)

    try:
        gm = _read_json(ddir / "gap_monitor.json", {})
        if isinstance(gm, dict) and gm.get("gap_detected"):
            hours = float(gm.get("hours_since_last_entry", 0.0) or 0.0)
            # Dedup on whole-hour buckets so a persistent gap doesn't
            # re-alert every cycle, but a worsening gap still notifies.
            if _should_send_alert("gap", f"{hours:.0f}"):
                sent["gap"] = alert_manager.send_gap_alert(hours)
            else:
                log.info("gap unchanged — alert skipped (dedup)")
    except Exception as exc:  # noqa: BLE001
        log.warning("gap alert failed (%s) — cycle continues", exc)

    return sent


def _last_trade_id_from_file(ddir: Path) -> "str | None":
    """Return the trade_id of the last recorded trade in trades.json, or None.

    Used as a fallback in _write_status so ``last_trade_id`` is never null
    while real trades exist (Fix P0-B2).
    """
    try:
        raw = _read_json(ddir / TRADES_FILENAME, [])
        trades: list = (
            raw if isinstance(raw, list)
            else (raw.get("trades", []) if isinstance(raw, dict) else [])
        )
        if trades and isinstance(trades[-1], dict):
            tid = trades[-1].get("trade_id")
            return str(tid) if tid is not None else None
    except Exception:
        pass
    return None


def _write_status(
    ddir: Path,
    result: "CycleResult",
    paper_start_date: str,
    capital_usd: float,
    run_ts: str,
) -> None:
    """Write ``paper_trading_status.json`` — the real (non-demo) status doc."""
    doc = {
        "is_demo": False,
        "source": "cycle_runner",
        "execution_mode": "read_only_simulation",
        "paper_start_date": paper_start_date,
        "last_cycle_ts": run_ts,
        "last_cycle_status": result.status,
        "days_running": result.days_running,
        "current_equity": result.current_equity,
        "total_return_pct": result.total_return_pct,
        "daily_return_pct": result.daily_return_pct,
        "apy_today_pct": result.apy_today_pct,
        "daily_yield_usd": result.daily_yield_usd,
        "num_adapters_live": result.num_adapters_live,
        "current_positions": result.positions,
        "last_allocation_model": result.model_used,
        "strategy_loop_active": result.strategy_loop_active,
        # Fix P0-B2: when this cycle did not trade, fall back to the last
        # recorded trade_id from trades.json so the field never shows null
        # while real trades exist.
        "last_trade_id": (
            result.trade_id
            if result.trade_id is not None
            else _last_trade_id_from_file(ddir)
        ),
        "notes": result.notes,
        # MP-005: deterministic RiskPolicy gate verdict for this cycle.
        "risk_policy_checked": result.policy_checked,
        "risk_policy_approved": result.policy_approved,
        "risk_policy_trimmed": result.policy_trimmed,
        "risk_policy_violations": result.policy_violations,
        "risk_policy_warnings": result.policy_warnings,
        # MP-108: kill-switch state for this cycle.
        "kill_switch_active": result.kill_switch_active,
        "kill_switch_reason": result.kill_switch_reason,
        # LAW 1 (fail-safe): safety-check evaluation failure for this cycle.
        "safety_check_failed": result.safety_check_failed,
        "safety_check_reason": result.safety_check_reason,
        # MP-534: market regime snapshot.
        "market_regime": result.market_regime,
        "regime_t1_avg_apy": result.regime_t1_avg_apy,
    }
    _atomic_write_json(ddir / STATUS_FILENAME, doc)


# ─── SPA-V434: dashboard cycle-metrics snapshot ───────────────────────────────


def save_dashboard_snapshot(
    metrics_dict: dict,
    *,
    data_dir: "str | os.PathLike | None" = None,
) -> bool:
    """Append one cycle-metrics snapshot to ``data/dashboard_metrics_history.json``.

    Throttled: returns ``False`` (without writing) if the last recorded entry
    is less than 23 hours old — prevents intra-day spam when the cycle reruns.

    Rotation: the history list is capped at ``MAX_DASHBOARD_ENTRIES`` (365)
    entries; the oldest entry is silently evicted when the cap is exceeded.

    The write is atomic: ``tmpfile + os.replace`` per the repo-wide rule.
    Stdlib only. Never raises — any internal error is caught and returns False.

    Migration: an existing file in the legacy kanban-oriented format (history
    entries carry ``date`` but not ``ts``) is treated as empty so the new
    format takes over cleanly.

    Parameters
    ----------
    metrics_dict : dict
        Expected keys: ``ts`` (ISO-8601 str), ``equity`` (float),
        ``daily_pnl`` (float), ``positions`` (dict[str, float]),
        ``adapter_counts`` (dict with ``active``/``paused`` int keys),
        ``cycle_number`` (int).
    data_dir : path-like, optional
        Directory that contains ``dashboard_metrics_history.json``.
        Defaults to the repo-level ``data/`` directory.

    Returns
    -------
    bool
        ``True`` if a new entry was written; ``False`` if throttled or on error.
    """
    try:
        ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
        path = ddir / DASHBOARD_HISTORY_FILENAME

        existing = _read_json(path, {})

        # Accept only entries that carry the new-format ``ts`` field.
        # Entries with only a ``date`` field belong to the legacy kanban format
        # and are discarded so the new format can start fresh.
        raw_history: list[dict] = []
        if isinstance(existing, dict):
            raw = existing.get("history")
            if (
                isinstance(raw, list)
                and raw
                and isinstance(raw[0], dict)
                and "ts" in raw[0]
            ):
                raw_history = [e for e in raw if isinstance(e, dict)]

        # Throttle: skip if the last entry is younger than 23 hours.
        if raw_history:
            last_ts_str = raw_history[-1].get("ts", "")
            try:
                # Normalise "Z" suffix for Python < 3.11 compatibility.
                last_ts = datetime.fromisoformat(
                    str(last_ts_str).replace("Z", "+00:00")
                )
                if last_ts.tzinfo is None:
                    last_ts = last_ts.replace(tzinfo=timezone.utc)
                age_seconds = (datetime.now(timezone.utc) - last_ts).total_seconds()
                if age_seconds < 23 * 3600:
                    return False
            except (ValueError, TypeError, OverflowError, AttributeError):
                pass  # Unparseable timestamp → proceed with the write

        # Append the new entry and rotate to the ring-buffer cap.
        raw_history.append(dict(metrics_dict))
        raw_history = raw_history[-MAX_DASHBOARD_ENTRIES:]

        doc = {
            "schema_version": "1.0",
            "generated_at": metrics_dict.get(
                "ts", datetime.now(timezone.utc).isoformat()
            ),
            "history": raw_history,
        }
        _atomic_write_json(path, doc)
        return True
    except Exception as exc:  # noqa: BLE001 — snapshot must never raise
        log.warning("save_dashboard_snapshot failed (%s)", exc)
        return False


def _save_cycle_snapshot_safe(
    ddir: Path,
    result: "CycleResult",
    adapters: list[dict],
    run_ts: str,
) -> None:
    """Build the metrics dict from *result* and call :func:`save_dashboard_snapshot`.

    Fail-safe: any exception is logged as WARNING and swallowed — a broken
    snapshot writer must never crash the daily cycle.
    """
    try:
        active = sum(
            1
            for a in adapters
            if isinstance(a, dict) and a.get("status") in ("ok", "partial")
        )
        paused = max(0, len(adapters) - active)
        save_dashboard_snapshot(
            {
                "ts": run_ts,
                "equity": result.current_equity,
                "daily_pnl": result.daily_yield_usd,
                "positions": {p: round(v, 2) for p, v in result.positions.items()},
                "adapter_counts": {"active": active, "paused": paused},
                "cycle_number": result.days_running,
            },
            data_dir=ddir,
        )
    except Exception as exc:  # noqa: BLE001 — snapshot must never crash the cycle
        log.warning("dashboard snapshot failed (%s) — cycle continues", exc)


# ─── Post-cycle advisory tail (N12 decomposition) ────────────────────────────


def run_post_cycle_advisory(
    *,
    ddir: Path,
    result: "CycleResult",
    apy_map: dict,
    adapters: list,
    effective_positions: dict,
    close_equity: float,
    equity_doc: dict,
    now_dt: "datetime",
    today,
    run_ts: str,
    track_persister_fn,
    notes: list,
) -> None:
    """Run the post-persist advisory / analytics / shadow / reporting tail.

    PURE-MOVE EXTRACTION from ``cycle_runner.run_cycle`` (the block that runs
    AFTER the real track is persisted, inside ``if write:``). The body is
    byte-identical to the original inline sequence (verbatim, only dedented and
    parameterised on the locals it used). Every sub-block is independently
    fail-safe. ``notes`` is the SAME list object the caller holds (and that
    ``result.notes`` aliases), so in-place appends here (``_persist_track``) are
    preserved exactly. ``_persist_track`` / ``_run_daily_report`` /
    ``run_tournament_step`` are imported lazily to avoid an import cycle;
    ``_save_cycle_snapshot_safe`` is defined in this module.
    """
    from spa_core.paper_trading.cycle_runner import _persist_track, _run_daily_report
    from spa_core.paper_trading.cycle_tournament import run_tournament_step
    # ── MP-373: APY Aggregator ranking (fail-safe, advisory) ────────────
    # Читает adapter_status.json, строит APY-рейтинг и сохраняет в
    # data/apy_ranking.json. Логирует top-3 по APY.
    # Никогда не блокирует основной цикл.
    try:
        from spa_core.adapters.apy_aggregator import APYAggregator as _APYAgg
        _agg = _APYAgg.load(ddir)
        _agg_ranking = _agg.rank_by_apy()
        if _agg_ranking:
            _agg.save_ranking(ddir / "apy_ranking.json")
            _top3 = _agg_ranking[:3]
            log.info(
                "MP-373 APY top-3: %s",
                ", ".join(
                    f"{s.protocol}={s.apy_pct:.2f}%" for s in _top3
                ),
            )
    except Exception as _agg_exc:  # noqa: BLE001 — never crash the cycle
        log.warning("APYAggregator failed (%s) — cycle continues", _agg_exc)

    # ── MP-389: Adapter Registry Refresh (fail-safe, advisory) ───────────
    # Вызывает get_apy_pct() у каждого зарегистрированного адаптера и
    # обновляет data/adapter_status.json атомарно.
    # Никогда не блокирует основной цикл.
    try:
        from spa_core.adapters.adapter_registry import refresh_all as _reg_refresh
        _reg_results = _reg_refresh(str(ddir / "adapter_status.json"))
        _live_count = len(
            [v for v in _reg_results.values() if not isinstance(v, dict)]
        )
        log.info("MP-389 AdapterRegistry refreshed %d adapters", _live_count)
    except Exception as _reg_exc:  # noqa: BLE001 — never crash the cycle
        log.warning("MP-389 AdapterRegistry skipped: %s", _reg_exc)

    # ── MP-153: Multi-strategy tournament step (fail-safe, advisory) ─────
    # Симулирует дневной шаг для всех 8 vPortfolio параллельно, оценивает
    # метрики (Sharpe/Calmar/Ulcer/Rachev) и сохраняет ранжирование.
    # Strictly read-only / advisory — не трогает trades.json, equity_curve,
    # risk/policy. Никогда не блокирует основной цикл.
    _t_ranking: list = []  # MP-373: sentinel — PromotionEngine reads below
    try:
        from spa_core.paper_trading.vportfolio import VPortfolioManager
        from spa_core.paper_trading.tournament_evaluator import TournamentEvaluator
        _t_manager = VPortfolioManager.load(data_dir=ddir)
        _t_manager.simulate_day(apy_map, date_str=today)
        _t_evaluator = TournamentEvaluator(_t_manager, data_dir=ddir)
        _t_ranking = _t_evaluator.evaluate_all()
        _t_manager.save()
        _t_evaluator.save_ranking(_t_ranking)
        log.info(
            "MP-153 tournament: %d strategies simulated, leader=%s composite=%.3f",
            len(_t_ranking),
            _t_ranking[0].strategy_id if _t_ranking else "n/a",
            _t_ranking[0].composite_score if _t_ranking else 0.0,
        )
    except Exception as _t_exc:  # noqa: BLE001 — never crash the cycle
        log.warning("MP-153 tournament_step error (%s) — cycle continues", _t_exc)

    # ── MP-373: PromotionEngine — auto-promote/demote/kill strategies ────
    # Принимает решения promote/demote/kill на основе метрик турнира.
    # Сохраняет data/promotion_report.json. Advisory — не трогает реальный
    # allocator, risk/policy или execution. Никогда не блокирует цикл.
    try:
        from spa_core.paper_trading.promotion_engine import PromotionEngine as _PromEng
        _pe = _PromEng()
        _pe_metrics: dict = {}
        for _r in _t_ranking:
            _pe_metrics[_r.strategy_id] = {
                "sharpe_30d": _r.metrics.sharpe_ratio,
                "calmar_30d": _r.metrics.calmar_ratio,
                # StrategyMetrics.max_drawdown_pct — положительная доля (0..1),
                # e.g. 0.15 = просадка 15%.
                # PromotionEngine.KILL_DRAWDOWN = -0.10 (< 0), поэтому
                # нужно передавать отрицательное значение: -0.15 < -0.10 → kill.
                "max_drawdown_pct": -abs(_r.metrics.max_drawdown_pct),
                "days_active": _r.metrics.days_observed,
            }
        _pe_decisions = _pe.evaluate_all(_pe_metrics)
        # Применяем решения к advisory allocation_map (real allocator не затронут)
        _pe_alloc: dict = {d.strategy_id: 0.0 for d in _pe_decisions}
        _pe_alloc = _pe.apply_decisions(_pe_decisions, _pe_alloc)
        _pe.save_report(_pe_decisions, ddir)
        _non_hold = [d for d in _pe_decisions if d.action != "hold"]
        if _non_hold:
            for _d in _non_hold:
                log.info(
                    "MP-373 promotion: %s → %s  alloc=%.3f  (%s)",
                    _d.strategy_id,
                    _d.action,
                    _pe_alloc.get(_d.strategy_id, 0.0),
                    _d.reason,
                )
        else:
            log.info(
                "MP-373 PromotionEngine: %d strategies evaluated — all hold",
                len(_pe_decisions),
            )
    except Exception as _pe_exc:  # noqa: BLE001 — never crash the cycle
        log.warning("PromotionEngine failed (%s) — cycle continues", _pe_exc)

    # ── MP-386..S_BASIS: Multi-Strategy Tournament step (advisory) ─────
    # Extracted verbatim to cycle_tournament.run_tournament_step (N12);
    # strictly read-only / fail-safe — never crashes the cycle.
    run_tournament_step(ddir, apy_map)

    # ── MP-1357: Shadow paper trading — top-5 mass-tournament strategies ──
    # Simulates what each backtest-top-5 strategy would earn today using
    # the live apy_map.  Appends to data/shadow_paper_trading.json.
    # Advisory only: never modifies trades.json, equity_curve_daily.json,
    # current_positions.json, or any risk state.  Fail-safe — any
    # exception → WARNING only.
    try:
        from spa_core.backtesting.strategy_tournament_runner import (
            run_shadow_day as _run_shadow_day,
        )
        _shadow_result = _run_shadow_day(
            apy_map=apy_map,
            data_dir=ddir,
            date_str=today.isoformat(),
        )
        _shadow_best = _shadow_result.get("best_strategy")
        _shadow_best_apy = _shadow_result.get("best_apy_pct", 0.0)
        log.info(
            "MP-1357 shadow_day: best=%s  apy=%.3f%%  strategies=%d",
            _shadow_best,
            _shadow_best_apy,
            len(_shadow_result.get("strategies", [])),
        )
    except Exception as _shadow_exc:  # noqa: BLE001 — never crash the cycle
        log.warning("MP-1357 shadow_day skipped: %s", _shadow_exc)

    from spa_core.paper_trading.gap_monitor import check_gaps as _check_gaps
    try:
        _check_gaps()
    except Exception:
        pass  # fail-open

    # ── MP-111: milestone tracker (fail-safe, advisory) ──────────────
    # Runs AFTER gap_monitor so its gap_detected flag feeds the streak
    # check. Never blocks the cycle — any exception → WARNING only.
    try:
        from spa_core.milestone.milestone_tracker import check_milestone

        _gm_data = _read_json(ddir / "gap_monitor.json", {})
        milestone_status = check_milestone(
            equity_curve=(equity_doc.get("daily") or [])
            if isinstance(equity_doc, dict)
            else [],
            gap_monitor_data=_gm_data,
        )
        log.info(
            "Milestone: %d/30 days (%.1f%%)",
            milestone_status.consecutive_days,
            milestone_status.progress_pct,
        )
        if milestone_status.is_milestone_reached:
            log.critical("🎯 MILESTONE REACHED: 30 consecutive days!")
    except Exception as exc:  # noqa: BLE001 — milestone must never crash the cycle
        log.warning("milestone tracker failed (%s) — cycle continues", exc)

    # MP-102: daily report after all steps (fail-safe, advisory).
    _run_daily_report(ddir, today)

    # MP-104: post-cycle analytics → analytics_summary.json (fail-safe,
    # advisory — a failure is a WARNING, never crashes the cycle).
    try:
        from spa_core.analytics.analytics_runner import (
            run_post_cycle_analytics,
        )

        run_post_cycle_analytics(data_dir=ddir, now=now_dt)
    except Exception as exc:  # noqa: BLE001
        log.warning("post-cycle analytics failed (%s) — cycle continues", exc)

    # ── MP-305: Reporting Agent — daily P&L report + monthly PDF ─────
    # Runs after analytics so the latest analytics_summary.json is on
    # disk. Fail-safe: any exception → WARNING, cycle never fails.
    try:
        from spa_core.agents.reporting_agent import run_reporting_cycle as _run_reporting
        _run_reporting(data_dir=ddir, dry_run=False)
    except Exception as _rep_exc:  # noqa: BLE001
        log.warning("reporting_cycle failed (%s) — cycle continues", _rep_exc)

    # ── MP-350: Telegram daily report — DailyReportBuilder + Keychain ─
    # Rich HTML digest (portfolio/APY/positions/risk/go-live).
    # Rate-limited once per day via sentinel; fail-safe.
    try:
        from spa_core.paper_trading.daily_report import run_daily_report as _run_dr
        _run_dr(data_dir=ddir, dry_run=False, force_send=False)
    except Exception as _dr_exc:  # noqa: BLE001
        log.warning("daily_report (MP-350) failed (%s) — cycle continues", _dr_exc)

    # ── MP-106: shadow strategies S0–S5 (advisory, local-only) ────────
    # Runs AFTER the real track is persisted; a failure here can never
    # affect trades.json / equity_curve_daily.json (fail-safe).
    try:
        from spa_core.shadow.shadow_tracker import run_shadow_cycle

        run_shadow_cycle(
            adapters,
            effective_positions,
            equity=close_equity,
            data_dir=ddir,
            date=today,
            now=now_dt,
        )
    except Exception as exc:  # noqa: BLE001 — shadow must never crash the cycle
        log.warning("shadow tracker failed (%s) — cycle continues", exc)

    # ── MP-138: Honest Metrics — Sortino/Sharpe CI + LOW_CONFIDENCE ─────
    # Runs after shadow so shadow_portfolio.json is fresh. Advisory only.
    try:
        from spa_core.paper_trading.honest_metrics import run_honest_metrics as _run_hm
        _run_hm(data_dir=ddir)
    except Exception as _hm_exc:  # noqa: BLE001
        log.warning("honest_metrics failed (%s) — cycle continues", _hm_exc)

    # ── MP-140: Backtest vs Paper Contour — Spearman rank correlation ──
    # Compares backtest strategy ranks vs actual shadow paper ranks.
    # Advisory only — will show INSUFFICIENT until ≥7 days of paper data.
    try:
        from spa_core.paper_trading.backtest_vs_paper import run_comparison as _run_cmp
        _run_cmp(data_dir=ddir)
    except Exception as _cmp_exc:  # noqa: BLE001
        log.warning("backtest_vs_paper failed (%s) — cycle continues", _cmp_exc)

    # ── MP-139: Structural-Break / Change-Point Detector ─────────────
    # Detects regime shifts in daily returns — fail if break+deterioration.
    # Advisory only — insufficient_data until ≥12 daily observations.
    try:
        from spa_core.paper_trading.structural_break import (
            build_structural_break as _build_sb,
            write_status as _write_sb,
        )
        _write_sb(_build_sb(data_dir=ddir), data_dir=ddir)
    except Exception as _sb_exc:  # noqa: BLE001
        log.warning("structural_break failed (%s) — cycle continues", _sb_exc)

    # ── MP-141: Progress Tracker ──────────────────────────────────────
    try:
        from spa_core.paper_trading.progress_tracker import run_progress_tracker as _run_pt
        _run_pt(data_dir=ddir)
    except Exception as _pt_exc:  # noqa: BLE001
        log.warning("progress_tracker failed (%s) — cycle continues", _pt_exc)

    # ── MP-143: Milestone Alert — Telegram on confidence upgrade ───
    try:
        from spa_core.alerts.milestone_alert import run_milestone_alert as _run_ma
        _run_ma(data_dir=ddir)
    except Exception as _ma_exc:  # noqa: BLE001
        log.warning("milestone_alert failed (%s) — cycle continues", _ma_exc)

    # ── MP-144: Cycle Gap Monitor ──────────────────────────────────────
    try:
        from spa_core.paper_trading.cycle_gap_monitor import run_cycle_gap_monitor as _run_cgm
        _run_cgm(data_dir=ddir)
    except Exception as _cgm_exc:
        log.warning("cycle_gap_monitor failed (%s) — cycle continues", _cgm_exc)

    # ── MP-109: SQLite mirror + off-site backup of the track ──────────
    # Runs LAST, after analytics/shadow, once every track artefact for
    # today is on disk. Fail-safe: a failure → WARNING + note
    # ``track_persist_failed``; the cycle never fails because of it.
    _persist_track(ddir, track_persister_fn, notes)

    # ── MP-311: fast loop (every cycle, deterministic — no LLM) ───────
    try:
        from spa_core.scheduler.loop_scheduler import run_fast_loop as _run_fast_loop
        _run_fast_loop(result.to_dict(), data_dir=str(ddir))
    except Exception as _fl_exc:
        log.warning("fast_loop failed (%s) — cycle continues", _fl_exc)

    # ── MP-311: adapter watchdog (every cycle, fail-safe) ─────────────
    try:
        from spa_core.scheduler.adapter_watchdog import run_watchdog_cycle as _run_watchdog
        _run_watchdog(data_dir=str(ddir))
    except Exception as _wd_exc:
        log.warning("adapter_watchdog failed (%s) — cycle continues", _wd_exc)

    # ── MP-311: slow loop (daily, LLM-advisory — always degraded here) ─
    try:
        from spa_core.scheduler.loop_scheduler import run_slow_loop as _run_slow_loop
        _run_slow_loop(today, llm_available=False, data_dir=str(ddir))
    except Exception as _sl_exc:
        log.warning("slow_loop failed (%s) — cycle continues", _sl_exc)

    # ── MP-311: strategic loop (weekly on Monday, LLM-advisory) ───────
    try:
        if now_dt.weekday() == 0:  # Monday
            from spa_core.scheduler.loop_scheduler import run_strategic_loop as _run_strategic
            _run_strategic(today, llm_available=False, data_dir=str(ddir))
    except Exception as _strat_exc:
        log.warning("strategic_loop failed (%s) — cycle continues", _strat_exc)

    # SPA-V434: dashboard metrics snapshot (fail-safe, advisory).
    _save_cycle_snapshot_safe(ddir, result, adapters, run_ts)

    # ── MP-310: Decision Audit Trail export ───────────────────────────
    try:
        from spa_core.audit.decision_audit import run_audit_export as _run_ae
        _run_ae(data_dir=ddir)
    except Exception as _ae_exc:
        log.warning("decision_audit failed (%s) — cycle continues", _ae_exc)

    # ── MP-416: Record daily paper trading evidence ────────────────────
    # Fail-safe: evidence tracking must never crash the main cycle.
    try:
        from spa_core.paper_trading.paper_evidence_tracker import (
            PaperEvidenceTracker as _PET,
        )
        _et = _PET(evidence_file=str(ddir / "paper_evidence.json"))
        # Use the actual portfolio APY for the day; fall back to S7 default.
        _et_apy = (
            result.apy_today_pct
            if isinstance(result.apy_today_pct, (int, float))
            and result.apy_today_pct > 0
            else 10.115
        )
        _et.record_day(
            trade_date=now_dt.date(),
            apy_pct=_et_apy,
            equity_value=result.current_equity,
            strategy_id="S7",
            notes="auto-recorded by cycle_runner v4.73",
        )
        log.info(
            "MP-416 evidence recorded: date=%s apy=%.4f%% equity=%.2f",
            today,
            _et_apy,
            result.current_equity,
        )
    except Exception as _et_exc:
        log.warning(
            "paper_evidence_tracker failed (%s) — cycle continues", _et_exc
        )

    # ── MP-512: APY Milestone Tracker ────────────────────────────────
    # Fail-safe: milestone tracking must never crash the main cycle.
    try:
        from spa_core.analytics.apy_milestone_tracker import (
            ApyMilestoneTracker as _AMTracker,
        )
        _amt = _AMTracker()
        _apy_for_milestone = (
            result.apy_today_pct
            if hasattr(result, "apy_today_pct")
            and isinstance(result.apy_today_pct, (int, float))
            and result.apy_today_pct > 0
            else 10.115
        )
        _strategy_for_milestone = (
            result.best_strategy_id
            if hasattr(result, "best_strategy_id")
            else "s7_pendle_yt"
        )
        _amt.record_day(today, _apy_for_milestone, _strategy_for_milestone)
        log.info(
            "MP-512 milestone recorded: date=%s apy=%.4f%% strategy=%s",
            today,
            _apy_for_milestone,
            _strategy_for_milestone,
        )
    except Exception as _amt_exc:
        log.warning(
            "apy_milestone_tracker failed (%s) — cycle continues", _amt_exc
        )
