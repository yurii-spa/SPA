#!/usr/bin/env python3
"""SPA paper-trading cycle runner (SPA-V409).

Closes the real, end-to-end paper-trading loop that until now was broken:

    orchestrator → allocator → trades.json → equity curve → status

One run == one "day" of paper trading:

1. Run the read-only adapter orchestrator → live APY/TVL snapshot.
2. Run the StrategyAllocator → target allocation (USD per pool).
2b. MP-005: pass the target through the deterministic ``RiskPolicy`` gate
   (``spa_core/risk/policy.py``) BEFORE any trade is recorded. A target that
   over-deploys past the min-cash buffer is trimmed proportionally (not
   blocked); any other violation (concentration caps, T2 total, TVL floor,
   APY bounds, drawdown kill switch) BLOCKS the rebalance: no trade is
   written, the block is appended to ``data/risk_policy_blocks.json``
   (ring-buffer 100) and the cycle continues holding the previous positions
   with ``status="blocked_by_policy"``. A failure inside the gate itself
   (unexpected exception) is logged as WARNING and the trade is BLOCKED
   (fail-closed, FIX-P0) — the cycle never crashes because of the gate.
3. If the (gate-approved) target allocation differs from the currently-held
   positions by more than ``trade_threshold_pct`` of capital → record a
   virtual ``rebalance`` trade in ``data/trades.json`` (ring-buffer, max 500).
4. Accrue one day of yield on the effective positions:
   ``daily_yield = position_usd * apy_pct / 100 / 365``.
5. Append/refresh today's point on the daily equity curve
   (``data/equity_curve_daily.json``, ring-buffer 365 days).
6. Refresh ``data/current_positions.json`` and ``data/paper_trading_status.json``
   (``is_demo: false`` — this is a *real* accumulating track record).

Safety / scope
==============
* STRICTLY READ-ONLY / SIMULATION. Touches NO real money and NO on-chain
  transactions. It only reads the orchestrator's read-only adapter snapshot and
  the allocator's advisory output, then writes paper-trading JSON.
* Does NOT import ``spa_core/execution/`` (wallet/router/signer/safety_checks),
  the feed-health stack, or any risk-agent capital-touching code. The only
  product modules it imports are the read-only orchestrator, the advisory
  allocator and — MP-005 — the strictly deterministic ``spa_core/risk/policy``
  (LLM-forbidden, pure in-memory checks: it reads no files, writes no files
  and touches no capital; its verdict gates whether a *virtual* trade is
  recorded).
* Stdlib only. All writes are atomic (tmpfile + os.replace).
* Idempotent per UTC day: re-running on the same calendar day refreshes that
  day's equity bar from the previous day's close rather than double-accruing,
  and emits no new trade when the allocation is unchanged.

equity_curve_daily.json schema note
====================================
This module writes ``equity_curve_daily.json`` as a **superset** of the schema
produced by ``equity_curve.py`` (the legacy demo derivation): it keeps the
existing ``summary`` roll-up and ``daily`` bar keys that the go-live criteria
(``readiness_checker.py`` C005 → ``summary.num_days``) and the performance
tearsheet read, and additionally exposes the flat ``equity`` / ``apy_today``
fields on each daily bar. Top-level ``is_demo: false`` / ``source:
"cycle_runner"`` mark it as the real track record.
"""
from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# ── N12 decomposition (PURE MOVE): shared primitives + extracted submodules ──
# The constants and atomic-IO helpers below historically lived in this file; they
# now live in ``_cycle_io`` so the extracted submodules can share them without a
# circular import. The three cohesive clusters (equity maintenance, the risk gate
# and the reporting/monitor tail) now live in dedicated modules. Every name is
# re-imported here so external callers/tests that ``from cycle_runner import X``
# keep working unchanged — this is a behaviour-preserving move, not a rewrite.
# Only the names this module USES internally plus those external callers/tests
# import ``from cycle_runner`` are re-imported here (the trimmed-down back-compat
# surface). Symbols with no remaining importer live solely in their new home.
from spa_core.paper_trading._cycle_io import (  # noqa: F401 — re-exported
    CAPITAL_USD,
    DASHBOARD_HISTORY_FILENAME,
    DEFAULT_TRADE_THRESHOLD_PCT,
    EQUITY_FILENAME,
    MAX_DASHBOARD_ENTRIES,
    MAX_TRADES,
    ORCH_STATUS_FILENAME,
    PAPER_REAL_START_DATE,
    PAPER_START_DATE,
    POSITIONS_FILENAME,
    RISK_SCORES_FILENAME,
    STATUS_FILENAME,
    TRADES_FILENAME,
    _atomic_write_json,
    _DEFAULT_DATA_DIR,
    _read_json,
    resolve_data_dir,
)
from spa_core.paper_trading.equity import (  # noqa: F401 — re-exported
    _accrue_daily_yield,
    _normalize_accrual_apy,
    _rebuild_summary,
    _upsert_equity_point,
    _write_equity,
)
from spa_core.paper_trading.risk_gate import (  # noqa: F401 — re-exported
    _apply_risk_policy_gate,
    _compliant_target,
    _record_policy_block,
)
from spa_core.paper_trading.cycle_gates import (  # noqa: F401 — re-exported
    apply_analytics_blocking_gate,
    apply_base_gas_kill_switch,
    apply_kill_switch_override,
    apply_rtmr_posture_gate,
    apply_soft_derisk_gate,
)
from spa_core.paper_trading.cycle_reporting import (  # noqa: F401 — re-exported
    _last_trade_id_from_file,
    _run_cycle_alerts,
    _run_daily_monitors,
    _save_cycle_snapshot_safe,
    _write_status,
    run_post_cycle_advisory,
    save_dashboard_snapshot,
)

# ADR-025 — Base chain gas kill-switch monitor (fail-safe optional import)
_BASE_GAS_MONITOR_CLASS: type[Any] | None
try:
    from spa_core.monitoring.base_gas_monitor import BaseGasMonitor as _BaseGasMonitor
    _BASE_GAS_MONITOR_CLASS = _BaseGasMonitor
    _BASE_CHAIN_MONITORING = True
except ImportError:
    _BASE_GAS_MONITOR_CLASS = None
    _BASE_CHAIN_MONITORING = False

# ── MP-534: Market Regime Detection ──────────────────────────────────────────
try:
    from spa_core.analysis.market_regime import MarketRegimeDetector as _MarketRegime
    _regime_detector = _MarketRegime()
except ImportError:
    _regime_detector = None

# ── Step 2b: Emergency Breakers (ADR-030) ────────────────────────────────────
try:
    from spa_core.risk.emergency_breakers import EmergencyBreakers as _EmergencyBreakers
    _emergency_breakers = _EmergencyBreakers()
except ImportError:
    _emergency_breakers = None

log = logging.getLogger("spa.cycle_runner")

# Configuration constants and atomic-IO helpers now live in
# ``spa_core/paper_trading/_cycle_io.py`` (N12 decomposition) and are re-imported
# at the top of this module for back-compat.


# ─── Result object ───────────────────────────────────────────────────────────


@dataclass
class CycleResult:
    """Outcome of a single cycle run (returned for tests / CLI reporting)."""

    run_ts: str
    date: str
    status: str  # "ok" | "skipped_no_live_data" | "blocked_by_policy"
    traded: bool
    trade_id: str | None
    live_data: bool
    num_adapters_live: int
    current_equity: float
    daily_yield_usd: float
    daily_return_pct: float
    apy_today_pct: float
    total_return_pct: float
    days_running: int
    model_used: str | None
    strategy_loop_active: bool
    positions: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    # MP-005: deterministic RiskPolicy gate (spa_core/risk/policy.py).
    policy_checked: bool = False
    policy_approved: bool = True
    policy_trimmed: bool = False
    policy_violations: list[str] = field(default_factory=list)
    policy_warnings: list[str] = field(default_factory=list)
    # MP-108: kill-switch state for this cycle.
    kill_switch_active: bool = False
    kill_switch_reason: str = ""
    # LAW-1 (fail-safe): a safety/risk check could not be evaluated this cycle.
    # When True, no NEW deployment/rebalance is allowed — current positions are
    # held and the cycle status is "blocked_safety_check_error".
    safety_check_failed: bool = False
    safety_check_reason: str = ""
    # MP-310: audit trail correlation id for this cycle.
    correlation_id: str = ""
    # MP-534: market regime snapshot for this cycle.
    market_regime: str = "UNKNOWN"
    regime_t1_avg_apy: float = 0.0

    def to_dict(self) -> dict:
        return {
            "run_ts": self.run_ts,
            "date": self.date,
            "status": self.status,
            "traded": self.traded,
            "trade_id": self.trade_id,
            "live_data": self.live_data,
            "num_adapters_live": self.num_adapters_live,
            "current_equity": self.current_equity,
            "daily_yield_usd": self.daily_yield_usd,
            "daily_return_pct": self.daily_return_pct,
            "apy_today_pct": self.apy_today_pct,
            "total_return_pct": self.total_return_pct,
            "days_running": self.days_running,
            "model_used": self.model_used,
            "strategy_loop_active": self.strategy_loop_active,
            "positions": self.positions,
            "notes": self.notes,
            "policy_checked": self.policy_checked,
            "policy_approved": self.policy_approved,
            "policy_trimmed": self.policy_trimmed,
            "policy_violations": self.policy_violations,
            "policy_warnings": self.policy_warnings,
            "kill_switch_active": self.kill_switch_active,
            "kill_switch_reason": self.kill_switch_reason,
            "safety_check_failed": self.safety_check_failed,
            "safety_check_reason": self.safety_check_reason,
            "correlation_id": self.correlation_id,
            "market_regime": self.market_regime,
            "regime_t1_avg_apy": self.regime_t1_avg_apy,
        }


# ─── LAW-1 fail-safe alert ───────────────────────────────────────────────────


def _send_safety_failsafe_alert(reason: str, correlation_id: str = "") -> None:
    """Loud Telegram alert when a safety/risk check could not be evaluated.

    LAW 1 (fail-safe, not fail-open): if a safety check raises, we cannot
    confirm trading is safe, so the cycle HOLDS (no new trades). This raises a
    human-visible alarm. Deterministic, stdlib + telegram_client only, never
    raises (alerting must not crash the cycle that is already degrading safely).
    """
    try:
        # Phase-1 Telegram rebuild: a fail-safe HOLD (safety check could not be
        # evaluated → cycle integrity at risk) is a genuine Tier-1 interrupt and
        # is routed through the SINGLE push authority (edge-triggered).
        from spa_core.telegram import push_policy  # noqa: PLC0415

        body = (
            "A risk/safety check could not be evaluated — the cycle is "
            "<b>HOLDING current positions</b> and suppressing all new "
            "deployment/rebalancing (LAW 1, fail-safe).\n\n"
            f"<b>Reason:</b> {reason}\n"
        )
        if correlation_id:
            body += f"<b>correlation_id:</b> {correlation_id}"
        push_policy.push_critical(
            "cycle_failed",
            "CRITICAL",
            "SPA FAIL-SAFE: safety check error",
            body,
        )
    except Exception as _alert_exc:  # noqa: BLE001
        log.warning("fail-safe push_policy alert failed (%s)", _alert_exc)


# ─── Pure helpers ────────────────────────────────────────────────────────────


def _live_apy_map(adapters: list[dict]) -> dict[str, float]:
    """protocol → live APY% for adapters that returned usable (ok/partial) data."""
    out: dict[str, float] = {}
    for a in adapters:
        if not isinstance(a, dict):
            continue
        if a.get("status") not in ("ok", "partial"):
            continue
        apy = a.get("apy_pct")
        if isinstance(apy, (int, float)):
            out[str(a.get("protocol"))] = float(apy)
    return out


def _sanity_apy_map(adapters: list[dict]) -> dict[str, float]:
    """adapter_id → live APY% for the DL-04/DL-05 sanity gate.

    Only adapters that actually returned a usable live yield are included.
    Records whose live feed was unavailable (``status`` not in {ok, partial},
    or no numeric ``apy_pct`` / ``apy``) are **excluded** rather than coerced to
    0.0 — feeding a None-as-0.0 into DL-04 fires a spurious "APY 0.00% below
    sanity floor (stale data?)" warning every time the upstream feed blips.

    Prefers the percentage field ``apy_pct`` and falls back to ``apy`` (also a
    percentage in adapter records). Returns ``{}`` when no adapter has live data.
    """
    out: dict[str, float] = {}
    for a in adapters:
        if not isinstance(a, dict):
            continue
        key = a.get("id") or a.get("protocol")
        if not key:
            continue
        # Honour the adapter's own liveness signal when present. Records with no
        # explicit status (legacy fixtures) are accepted if they carry a number.
        status = a.get("status")
        if status is not None and status not in ("ok", "partial"):
            continue
        apy = a.get("apy_pct")
        if not isinstance(apy, (int, float)):
            apy = a.get("apy")
        if not isinstance(apy, (int, float)):
            continue
        out[str(key)] = float(apy)
    return out


def _allocation_diff_usd(current: dict[str, float], target: dict[str, float]) -> float:
    """L1 distance (sum of absolute per-pool USD deltas) between two allocations."""
    keys = set(current) | set(target)
    return sum(abs(float(target.get(k, 0.0)) - float(current.get(k, 0.0))) for k in keys)


def _next_trade_id(trades: list[dict]) -> str:
    """Next sequential trade id ``T001``, ``T002`` … based on existing records."""
    max_n = 0
    for t in trades:
        tid = t.get("trade_id") if isinstance(t, dict) else None
        if isinstance(tid, str) and tid.startswith("T"):
            try:
                max_n = max(max_n, int(tid[1:]))
            except ValueError:
                continue
    return f"T{max_n + 1:03d}"


def _days_running(today: str, start: str = PAPER_START_DATE) -> int:
    """Calendar days elapsed since paper-trading start (inclusive, ≥ 1)."""
    try:
        d0 = datetime.strptime(start, "%Y-%m-%d").date()
        d1 = datetime.strptime(today, "%Y-%m-%d").date()
        return max(1, (d1 - d0).days + 1)
    except ValueError:
        return 1


# Equity-curve maintenance (_rebuild_summary / _upsert_equity_point /
# _write_equity) now lives in ``spa_core/paper_trading/equity.py``; the
# deterministic RiskPolicy gate (_apply_risk_policy_gate / _record_policy_block
# / _policy_version / _compliant_target) now lives in
# ``spa_core/paper_trading/risk_gate.py`` (N12 decomposition). Both are
# re-imported at the top of this module for back-compat.


# ─── MP-006: go-live anti-demo gate (advisory, never blocks the cycle) ───────


def _run_golive_gate(ddir: Path, now_dt: datetime, write: bool) -> None:
    """Refresh ``data/golive_status.json`` via ``GoLiveChecker`` (MP-006).

    Advisory only: a ``ready=False`` verdict is logged as a WARNING on the
    first run of each UTC day, and the cycle ALWAYS continues — it must keep
    running to accumulate the real track record the criteria wait for. Any
    failure inside the checker itself is logged and swallowed (fail-open).
    """
    try:
        from spa_core.paper_trading.golive_checker import (
            STATUS_OUT_FILENAME,
            GoLiveChecker,
        )

        prev = _read_json(ddir / STATUS_OUT_FILENAME, {})
        prev_date = (
            str(prev.get("timestamp", ""))[:10] if isinstance(prev, dict) else ""
        )
        result = GoLiveChecker(data_dir=ddir, now=now_dt).check(write=write)
        if not result.ready and prev_date != now_dt.strftime("%Y-%m-%d"):
            log.warning(
                "Go-live NOT ready (%d blockers): %s",
                len(result.blockers),
                "; ".join(result.blockers),
            )
    except Exception as exc:  # the gate must never crash the cycle
        log.warning("GoLiveChecker failed (%s) — cycle continues", exc)


# ─── MP-102: daily report (fail-safe, advisory — never blocks the cycle) ─────


def _run_daily_report(ddir: Path, date: str) -> None:
    """Generate ``data/daily_report_{date}.json`` for the cycle just run.

    Fail-safe per MP-102: any exception is logged as WARNING and swallowed —
    a broken report must never crash the daily cycle.
    """
    try:
        from spa_core.reporting.daily_report import generate_daily_report

        generate_daily_report(date, data_dir=ddir)
    except Exception as exc:  # noqa: BLE001 — reporting must never crash the cycle
        log.warning("daily report generation failed (%s) — cycle continues", exc)


# ─── Default orchestrator / allocator wiring (overridable for tests) ─────────


def _default_orchestrator(data_dir: Path) -> Any:
    """Run the real read-only adapter orchestrator (writes its status file)."""
    from spa_core.orchestrator.adapter_orchestrator import run_orchestrator

    return run_orchestrator(write=True, data_dir=str(data_dir))


def _default_allocator(data_dir: Path) -> Any:
    """Construct the real StrategyAllocator bound to this data dir's snapshot.

    ADR-033: the shadow→allocator feedback loop only steers the real allocation
    in ``"active"`` mode. In ``"off"``/``"shadow"`` modes the allocator is built
    with ``strategy_loop_enabled=False`` so the real target is never altered —
    the tournament still runs/logs separately as advisory-only. Reading the
    config is fail-safe: any error degrades to the ADR-033 default (shadow ⇒
    loop disabled in the allocator)."""
    from spa_core.allocator.allocator import StrategyAllocator

    loop_enabled = False
    try:
        from spa_core.strategies.strategy_config import loop_enabled_for_allocator
        loop_enabled = loop_enabled_for_allocator(data_dir=str(data_dir))
    except Exception as exc:  # never crash allocator construction on config read
        log.warning("ADR-033 allocator config read failed (%s) — loop disabled", exc)

    return StrategyAllocator(
        status_path=str(data_dir / ORCH_STATUS_FILENAME),
        strategy_loop_enabled=loop_enabled,
    )


def _default_risk_scorer(data_dir: Path) -> None:
    """MP-012: regenerate ``data/risk_scores.json`` via the scoring engine.

    Invocation only — ALL scoring logic stays in
    ``spa_core/risk/scoring_engine.py`` (the cycle runner never computes a
    score itself; the allocator then reads the refreshed JSON snapshot).
    The engine writes atomically (tmpfile + os.replace) and is itself
    offline-tolerant (network failure → bootstrap fallback, never raises for
    that reason).
    AUDIT-011: risk-layer must not make live HTTP calls (prompt-injection
    vector via DeFiLlama response). Pass offline=True so the engine uses
    BOOTSTRAP_PROTOCOLS — stable, audited, no network dependency."""
    from spa_core.risk.scoring_engine import RiskScoringEngine

    RiskScoringEngine(offline=True).export(output_file=Path(data_dir) / RISK_SCORES_FILENAME)


def _refresh_risk_scores(
    ddir: Path,
    risk_scorer_fn: Callable[[Path], Any] | None,
    notes: list[str],
) -> bool:
    """MP-012 fail-safe wrapper: any exception → WARNING + note, cycle
    continues on the previous (stale) ``risk_scores.json``. Never raises."""
    try:
        (risk_scorer_fn or _default_risk_scorer)(ddir)
        return True
    except Exception as exc:  # noqa: BLE001 — regen must never crash the cycle
        log.warning(
            "risk_scores.json regeneration failed (%s) — allocator continues "
            "on the previous snapshot",
            exc,
        )
        notes.append(
            f"risk_scores_regen_failed: {type(exc).__name__}: {exc} — "
            "cycle continues on the stale risk_scores.json."
        )
        return False


TRACK_PERSIST_STATUS_FILENAME = "track_persist_status.json"


def _verify_track_db(db_path: Path) -> tuple[bool, int, str]:
    """Open ``track.db`` and assert it is a non-empty, integrity-clean SQLite
    mirror. Returns ``(ok, size_bytes, reason)``. Never raises.

    This is the guard that turns the historical *silent* 0-byte failure into an
    observable one: a freshly-published mirror that is 0 bytes (e.g. a direct
    ``sqlite3.connect`` left a header-less stub, an interrupted publish, or a
    git/working-tree restore truncated the file) is reported as NOT-ok with a
    concrete reason instead of passing for a healthy DB.
    """
    import sqlite3

    try:
        size = db_path.stat().st_size if db_path.exists() else 0
    except OSError as exc:
        return False, 0, f"stat failed: {exc}"
    if size == 0:
        return False, 0, "track.db is 0 bytes (empty/stub mirror)"
    try:
        # allow-raw-sqlite-connect: sqlite-native PRAGMA integrity_check on the local
        # track.db mirror; no postgres equivalent, so it cannot use the DB abstraction.
        conn = sqlite3.connect(os.fspath(db_path))  # allow-raw-sqlite-connect
        try:
            integ = conn.execute("PRAGMA integrity_check").fetchone()
            if not integ or integ[0] != "ok":
                return False, size, f"integrity_check={integ[0] if integ else 'None'}"
            # A mirror with neither table populated is as useless as a 0-byte file.
            n_eq = conn.execute("SELECT COUNT(*) FROM equity_curve").fetchone()[0]
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 — verification must never raise
        return False, size, f"sqlite open/query failed: {type(exc).__name__}: {exc}"
    if n_eq == 0:
        return False, size, "track.db has 0 equity_curve rows"
    return True, size, "ok"


def _default_track_persister(data_dir: Path) -> dict:
    """MP-109: mirror the track into SQLite, VERIFY it, then run the off-site
    backup. Returns a structured result; never raises.

    ALL persistence logic lives in ``spa_core/persistence/track_store.py``
    (idempotent SQLite mirror of ``trades.json`` / ``equity_curve_daily.json``;
    the JSON files stay the source of truth and are NEVER modified) and
    ``spa_core/persistence/backup.py`` (dated folder on iCloud Drive /
    ``$SPA_BACKUP_DIR``, sha256 manifest, 14-folder rotation).

    ROOT-CAUSE DECOUPLING (the historical 0-byte ``data/track.db`` bug): the
    local SQLite mirror is the machine's crash-recovery copy and MUST succeed
    independently of the off-site backup. The mirror is therefore synced AND
    verified FIRST; only then is ``run_backup`` attempted. A backup failure
    (missing / unwritable ``$SPA_BACKUP_DIR`` or iCloud path) can no longer
    prevent or mask the local ``track.db`` write — its error is recorded
    separately and never poisons ``mirror_ok``.
    """
    from spa_core.persistence.backup import run_backup
    from spa_core.persistence.track_store import TrackStore

    ddir = Path(data_dir)
    db_path = ddir / "track.db"

    # 1) Local mirror FIRST and independently — this is crash-recovery, it must
    #    write to data/track.db regardless of the offsite/backup dir's state.
    sync = TrackStore(db_path=db_path).sync_from_json(ddir)
    mirror_ok, db_size, verify_reason = _verify_track_db(db_path)
    mirror_ok = mirror_ok and sync.get("status") == "ok"

    # 2) Off-site backup SECOND and decoupled — its outcome is reported but can
    #    never flip mirror_ok (a missing $SPA_BACKUP_DIR/iCloud is not a local
    #    crash-recovery failure).
    backup = run_backup(ddir)

    return {
        "mirror_ok": bool(mirror_ok),
        "db_size_bytes": int(db_size),
        "sync_status": sync.get("status"),
        "sync_errors": list(sync.get("errors") or []),
        "verify_reason": verify_reason,
        "equity_points_total": sync.get("equity_points_total"),
        "trades_total": sync.get("trades_total"),
        "backup_status": backup.get("status"),
        "backup_errors": list(backup.get("errors") or []),
    }


def _write_track_persist_status(
    ddir: Path, *, ok: bool, reason: str, detail: dict | None = None
) -> None:
    """Persist an OBSERVABLE track-persist health flag so agent_health /
    monitoring can SEE a mirror failure that the cycle's ``status:ok`` would
    otherwise hide. Atomic; never raises."""
    try:
        doc = {
            "track_persist_ok": bool(ok),
            "reason": reason,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if detail:
            doc.update(detail)
        _atomic_write_json(ddir / TRACK_PERSIST_STATUS_FILENAME, doc)
    except Exception as exc:  # noqa: BLE001 — status-write must never crash the cycle
        log.warning("track_persist_status write failed (%s)", exc)


def _persist_track(
    ddir: Path,
    track_persister_fn: Callable[[Path], Any] | None,
    notes: list[str],
) -> bool:
    """MP-109 fail-safe wrapper. The cycle NEVER fails because of
    persistence/backup, but the outcome is now OBSERVABLE rather than silently
    swallowed:

    * an exception OR a verified-bad mirror (0-byte / corrupt / empty
      ``track.db``) → WARNING + ``note`` + ``track_persist_status.json``
      ``track_persist_ok:false`` with a concrete reason;
    * a healthy publish → ``track_persist_ok:true`` + db size.

    Never raises."""
    try:
        result = (track_persister_fn or _default_track_persister)(ddir)
    except Exception as exc:  # noqa: BLE001 — persistence must never crash the cycle
        reason = f"{type(exc).__name__}: {exc}"
        log.error(
            "track persistence/backup raised (%s) — cycle continues; the JSON "
            "track record is unaffected, but track.db was NOT refreshed",
            reason,
        )
        notes.append(
            f"track_persist_failed: {reason} — "
            "cycle continues; JSON track record unaffected."
        )
        _write_track_persist_status(ddir, ok=False, reason=reason)
        return False

    # An injected persister may return None (legacy contract) — treat a clean
    # return as success but still verify the on-disk mirror so a silently-empty
    # track.db can never again pass as healthy.
    detail = result if isinstance(result, dict) else {}
    mirror_ok, db_size, verify_reason = _verify_track_db(ddir / "track.db")
    if isinstance(result, dict):
        mirror_ok = bool(result.get("mirror_ok"))
        db_size = int(result.get("db_size_bytes") or db_size)
        verify_reason = result.get("verify_reason") or verify_reason

    if not mirror_ok:
        log.error(
            "track.db mirror is UNHEALTHY after persist (%s, %d bytes) — cycle "
            "continues but the SQLite track mirror was NOT refreshed; "
            "track_persist_ok=false flagged for monitoring",
            verify_reason,
            db_size,
        )
        notes.append(
            f"track_persist_failed: mirror unhealthy ({verify_reason}, "
            f"{db_size} bytes) — cycle continues; JSON track record unaffected."
        )
        _write_track_persist_status(
            ddir, ok=False, reason=verify_reason, detail={"db_size_bytes": db_size, **detail}
        )
        return False

    _write_track_persist_status(
        ddir, ok=True, reason="ok",
        detail={"db_size_bytes": db_size, **detail},
    )
    return True


# ─── Public entry point ──────────────────────────────────────────────────────


def run_cycle(
    *,
    data_dir: str | os.PathLike | None = None,
    now: datetime | None = None,
    capital_usd: float = CAPITAL_USD,
    paper_start_date: str = PAPER_START_DATE,
    trade_threshold_pct: float = DEFAULT_TRADE_THRESHOLD_PCT,
    orchestrator_fn: Callable[[Path], Any] | None = None,
    allocator: Any | None = None,
    risk_scorer_fn: Callable[[Path], Any] | None = None,
    track_persister_fn: Callable[[Path], Any] | None = None,
    write: bool = True,
    allow_live_write: bool = False,
) -> CycleResult:
    """Execute one paper-trading cycle.

    Parameters
    ----------
    data_dir   : directory for data/*.json (default <repo>/data).
    now        : injectable timestamp source (UTC) for deterministic tests.
    orchestrator_fn : ``(data_dir) -> result`` with ``.adapters`` (list[dict]),
                 ``.status`` ("ok"/"no_live_data"). Default runs the real
                 read-only orchestrator.
    allocator  : object exposing ``.allocate()`` → result with ``.target_usd``
                 (dict pool→USD), ``.expected_apy_pct``, ``.model_used``,
                 ``.strategy_loop_active``. Default = real StrategyAllocator
                 reading this data dir's orchestrator snapshot.
    risk_scorer_fn : MP-012 — ``(data_dir) -> None`` regenerating
                 ``risk_scores.json`` BEFORE the allocation step. Default runs
                 the real scoring engine (``spa_core/risk/scoring_engine``).
                 Fail-safe: an exception inside it is logged as WARNING and the
                 cycle continues on the previous (stale) snapshot.
    track_persister_fn : MP-109 — ``(data_dir) -> None`` mirroring the track
                 into SQLite and running the daily off-site backup AFTER all
                 track artefacts are persisted (post analytics/shadow). Default
                 = ``_default_track_persister`` (TrackStore.sync_from_json +
                 backup.run_backup). Fail-safe: an exception is logged as
                 WARNING + note ``track_persist_failed``; the cycle never fails
                 because of persistence. Skipped on dry-run.
    write      : if False, computes everything but writes nothing (dry-run;
                 risk_scores.json is NOT regenerated either).
    allow_live_write : track-integrity write-interlock (fail-CLOSED, default
                 DENY). Only when True (or env ``SPA_ALLOW_LIVE_WRITE=1``) may a
                 cycle write the canonical live track at ``<repo>/data``. Without
                 opt-in, a run targeting the canonical dir is REROUTED to a
                 sandbox (``SPA_DATA_DIR`` or a temp dir) so a stray dev-shell
                 ``python3 -m spa_core.paper_trading.cycle_runner`` can never
                 overwrite the honest track. An explicit non-canonical
                 ``data_dir`` is always honoured verbatim. See
                 ``_cycle_io.resolve_data_dir``.
    """
    ddir, _interlock_redirected = resolve_data_dir(
        data_dir, allow_live_write=allow_live_write
    )
    now_dt = now or datetime.now(timezone.utc)
    run_ts = now_dt.isoformat()
    today = now_dt.strftime("%Y-%m-%d")
    notes: list[str] = []

    orchestrator_fn = orchestrator_fn or _default_orchestrator

    # ── MP-310: begin audit trail chain for this cycle (fail-safe) ────────
    _correlation_id: str = ""
    try:
        from spa_core.audit.audit_trail import begin_cycle as _audit_begin
        _correlation_id = _audit_begin(today, data_dir=str(ddir))
    except Exception as _audit_exc:
        log.warning("audit begin_cycle failed (%s) — cycle continues", _audit_exc)

    # ── Step 0-pre (MP-1195): refresh adapter_status.json (v2 format) ────────
    # Regenerates adapter_status.json from adapter_registry.json + optional
    # DeFiLlama live APY.  Fail-safe: any error here is a WARNING; cycle
    # continues with the existing file on disk.  Skipped on dry-run.
    if write:
        try:
            from spa_core.monitoring.adapter_status_generator import (
                run_and_write as _asg_run,
            )
            _asg_run()
            log.info("MP-1195 adapter_status_generator: adapter_status.json refreshed")
        except Exception as _asg_exc:  # never crash the cycle
            log.warning(
                "MP-1195 adapter_status_generator skipped (%s) — cycle continues",
                _asg_exc,
            )

    # ── Step 0 (MP-006): go-live anti-demo gate — advisory, never blocks ──
    _run_golive_gate(ddir, now_dt, write)

    # ── Step 0a-pre (ADR-031 / MP-1146): refresh Tier-B advisory analytics ──
    # Run the advisory aggregator BEFORE risk_scores regeneration so that the
    # scoring_engine's analytics_composite subscore reads fresh signals. The
    # aggregator is TTL-cached (1h), parallel and fail-open; any exception here
    # degrades to a WARNING + note and the cycle continues. Skipped on dry-run.
    # CI/offline guard: skipped under SPA_ENV=ci — the aggregator spawns a thread
    # pool of modules that make live network calls; on CI those stall and the
    # pool's shutdown(wait=True) wedges the run (a HANG is not caught by the
    # fail-open except). Since the step is advisory/fail-open, skipping it in CI is
    # equivalent to its already-handled failure; the money-path cycle is unchanged.
    if write and os.environ.get("SPA_ENV") != "ci":
        try:
            from spa_core.analytics.signal_aggregator import (
                run_tier_b as _analytics_tier_b,
                DEFAULT_PROTOCOLS as _ANALYTICS_PROTOS,
            )
            _analytics_tier_b(
                list(_ANALYTICS_PROTOS),
                context={"cycle_ts": run_ts},
                data_dir=ddir,
            )
        except Exception as _ab_exc:  # never crash the cycle
            log.warning(
                "Tier-B analytics refresh failed (%s) — fail-open, cycle continues",
                _ab_exc,
            )
            notes.append(f"analytics_tier_b_error: {type(_ab_exc).__name__}")

    # ── Step 0b (MP-012): regenerate risk_scores.json BEFORE allocation ───
    # Fail-safe: a failure here degrades to a WARNING + note, and the
    # allocator (Step 2) keeps reading the previous snapshot. Skipped on
    # dry-run (write=False) so a dry-run leaves no files behind.
    if write:
        _refresh_risk_scores(ddir, risk_scorer_fn, notes)

    # ── Step 1: orchestrator → live APY snapshot ──────────────────────────
    orch = orchestrator_fn(ddir)
    adapters = list(getattr(orch, "adapters", None) or [])
    orch_status = getattr(orch, "status", "ok")
    apy_map = _live_apy_map(adapters)
    live = bool(apy_map) and orch_status != "no_live_data"
    # N3(b): pools whose APY came from a FALLBACK file (not the live feed) — used
    # to stamp the equity bar's accrual_source so a fallback-accrued day is auditable.
    _fallback_apy_pools: set[str] = set()

    # ── MP-413: merge fallback APY values for adapters NOT in orchestrator ──
    # The orchestrator covers: aave_v3, compound_v3, morpho_blue, yearn_v3,
    # euler_v2, maple.  Newer adapters (morpho_steakhouse, pendle_pt, etc.)
    # are absent from apy_map; strategies fall back to hardcoded constants.
    # We merge their values from adapter_status.json (best available data)
    # as a safe fallback — only for keys genuinely missing from apy_map and
    # only when the value is a positive float.  Never overwrites live data.
    # MP-1195: supports both v1 (top-level protocol keys) and v2 (nested
    # "adapters" dict) formats by using .get("adapters", doc) with fallback.
    try:
        _adapter_status = _read_json(ddir / "adapter_status.json", {})
        if isinstance(_adapter_status, dict):
            # v2: adapters is a nested dict; v1: iterate top-level keys
            _as_adapters = _adapter_status.get("adapters", _adapter_status)
            if not isinstance(_as_adapters, dict):
                _as_adapters = _adapter_status
            for _proto_key, _entry in _as_adapters.items():
                if _proto_key in apy_map:
                    continue  # live orchestrator value takes precedence
                if not isinstance(_entry, dict):
                    continue
                _fallback_apy = _entry.get("apy")
                if isinstance(_fallback_apy, (int, float)) and _fallback_apy > 0:
                    apy_map[_proto_key] = float(_fallback_apy)
                    _fallback_apy_pools.add(str(_proto_key))  # N3(b)
                    log.debug(
                        "MP-413 apy_map[%s]=%.4f (adapter_status.json fallback)",
                        _proto_key,
                        _fallback_apy,
                    )
    except Exception as _mp413_exc:  # never crash the cycle
        log.warning("MP-413 apy_map merge failed (%s) — cycle continues", _mp413_exc)

    # ── Fix P0-B1: registry fallback APY for yield accrual ───────────────────
    # Problem: _accrue_daily_yield skips any pool absent from apy_map → with
    # only 1 live adapter, 23 deployed positions accrue $0 yield (8× collapse).
    # Fix: fill apy_map gaps from adapter_registry.json fallback_apy (decimal
    # fraction, e.g. 0.035 = 3.5%) so every position contributes its expected
    # yield.  Live orchestrator data already in apy_map is never overwritten.
    try:
        _yield_reg_doc = _read_json(ddir / "adapter_registry.json", {})
        _yield_reg_adapters = (
            _yield_reg_doc.get("adapters", {})
            if isinstance(_yield_reg_doc, dict)
            else {}
        )
        if isinstance(_yield_reg_adapters, dict):
            for _yrk, _yrv in _yield_reg_adapters.items():
                if _yrk in apy_map:
                    continue  # live / MP-413 value takes precedence
                if not isinstance(_yrv, dict):
                    continue
                _yr_fb = _yrv.get("live_apy") or _yrv.get("fallback_apy")
                if isinstance(_yr_fb, (int, float)) and _yr_fb > 0:
                    apy_map[_yrk] = float(_yr_fb) * 100.0  # fraction → pct
                    _fallback_apy_pools.add(str(_yrk))  # N3(b)
                    log.debug(
                        "P0-B1 apy_map[%s]=%.3f%% (registry fallback, yield accrual)",
                        _yrk,
                        float(_yr_fb) * 100.0,
                    )
    except Exception as _yr_exc:
        log.warning("P0-B1 yield registry fallback failed (%s) — cycle continues", _yr_exc)

    # ── MP-534: Detect market regime ─────────────────────────────────────────
    _regime_name: str = "UNKNOWN"
    _regime_t1_avg_apy: float = 0.0
    if _regime_detector is not None and apy_map:
        try:
            _regime_result = _regime_detector.detect(apy_map)
            # Write to the cycle's own ddir (not the module-level default path).
            _atomic_write_json(ddir / "market_regime.json", _regime_result)
            _regime_name = _regime_result.get("regime", "UNKNOWN")
            _regime_t1_avg_apy = float(_regime_result.get("t1_avg_apy", 0.0))
            log.info(
                "MP-534 market_regime=%s t1_avg_apy=%.4f%%",
                _regime_name,
                _regime_t1_avg_apy,
            )
        except Exception as _rd_exc:  # never crash the cycle
            log.warning("MP-534 regime detection failed (%s) — cycle continues", _rd_exc)

    # Load prior persisted state up front (needed for both paths).
    current_positions: dict[str, float] = {
        k: float(v)
        for k, v in (_read_json(ddir / POSITIONS_FILENAME, {}).get("positions", {}) or {}).items()
    }

    # ── ALLOC-001: validate current positions; trigger rebalancer on violations ──
    # Fail-safe: any exception here must never block the cycle (advisory gate).
    # Rebalancer runs ONLY when current positions violate policy — it is not run
    # every cycle to avoid unnecessary churn in the positions file.
    try:
        from spa_core.risk.policy_enforcer import validate_positions as _pe_validate
        _pos_cash = capital_usd - sum(current_positions.values())
        _pos_check = _pe_validate(
            positions=current_positions if current_positions else None,
            capital_usd=capital_usd,
            cash_usd=_pos_cash,
        )
        if not _pos_check.passed:
            _alloc001_rules = [v.rule for v in _pos_check.violations]
            log.warning(
                "ALLOC-001: current positions violate policy (%s) — "
                "triggering portfolio_rebalancer",
                _alloc001_rules,
            )
            notes.append(
                "ALLOC-001: policy violations detected {}; triggering rebalancer".format(
                    _alloc001_rules
                )
            )
            try:
                from spa_core.tuner.portfolio_rebalancer import rebalance_portfolio as _rb
                _rb_ok = _rb(
                    capital_usd=capital_usd,
                    data_dir=ddir,
                    write=write,
                    send_alert=True,
                )
                if _rb_ok:
                    # Reload positions after successful rebalance
                    current_positions = {
                        k: float(v)
                        for k, v in (
                            _read_json(ddir / POSITIONS_FILENAME, {}).get("positions", {}) or {}
                        ).items()
                    }
                    notes.append("ALLOC-001: rebalancer succeeded — positions reloaded")
                    log.info("ALLOC-001: rebalancer applied new positions")
                else:
                    notes.append(
                        "ALLOC-001: rebalancer rejected allocation — keeping existing positions"
                    )
                    log.warning("ALLOC-001: rebalancer returned False — positions unchanged")
            except Exception as _rb_exc:
                log.warning(
                    "ALLOC-001: portfolio_rebalancer import/run failed (%s) — "
                    "cycle continues with existing positions",
                    _rb_exc,
                )
                notes.append(
                    "ALLOC-001: rebalancer error: {}".format(type(_rb_exc).__name__)
                )
        else:
            log.debug("ALLOC-001: current positions passed policy check — no rebalance needed")
    except Exception as _alloc001_exc:
        log.warning(
            "ALLOC-001: policy check failed (%s) — skipping rebalancer, cycle continues",
            _alloc001_exc,
        )
        notes.append(
            "ALLOC-001: policy_check_error: {}".format(type(_alloc001_exc).__name__)
        )

    # Continue the equity curve ONLY if it is our own real track record. A
    # legacy demo-derived equity_curve_daily.json (written by equity_curve.py
    # from is_demo pnl_history) must NOT seed the real curve — otherwise the
    # real paper-trading record would inherit the demo's equity/drawdown. On the
    # first real cycle we archive the demo file once and start fresh at capital.
    raw_equity_doc = _read_json(ddir / EQUITY_FILENAME, {})
    is_real_curve = (
        isinstance(raw_equity_doc, dict)
        and raw_equity_doc.get("source") == "cycle_runner"
    )
    if is_real_curve:
        equity_doc = raw_equity_doc
    else:
        if isinstance(raw_equity_doc, dict) and raw_equity_doc.get("daily") and write:
            _atomic_write_json(ddir / "equity_curve_daily.demo_backup.json", raw_equity_doc)
            notes.append(
                "archived legacy demo equity_curve_daily.json → "
                "equity_curve_daily.demo_backup.json; started a fresh real curve."
            )
        equity_doc = {}
    prior_daily = equity_doc.get("daily") if isinstance(equity_doc, dict) else None
    prev_equity = (
        float(prior_daily[-1]["close_equity"])
        if isinstance(prior_daily, list) and prior_daily
        else capital_usd
    )

    # ── Graceful no-live-data: skip trading & accrual, surface honestly ───
    if not live:
        notes.append(
            "no_live_data: orchestrator returned no usable adapter APY — "
            "skipped trade & yield accrual for this cycle."
        )
        days = _days_running(today, paper_start_date)
        result = CycleResult(
            run_ts=run_ts,
            date=today,
            status="skipped_no_live_data",
            traded=False,
            trade_id=None,
            live_data=False,
            num_adapters_live=0,
            current_equity=round(prev_equity, 2),
            daily_yield_usd=0.0,
            daily_return_pct=0.0,
            apy_today_pct=0.0,
            total_return_pct=round((prev_equity / capital_usd - 1.0) * 100.0, 4),
            days_running=days,
            model_used=None,
            strategy_loop_active=False,
            positions=current_positions,
            notes=notes,
            correlation_id=_correlation_id,
            market_regime=_regime_name,
            regime_t1_avg_apy=_regime_t1_avg_apy,
        )
        if write:
            _write_status(ddir, result, paper_start_date, capital_usd, run_ts)
            # MP-102: daily report after all steps (fail-safe, advisory).
            _run_daily_report(ddir, today)
            # SPA-V434: dashboard metrics snapshot (fail-safe, advisory).
            _save_cycle_snapshot_safe(ddir, result, adapters, run_ts)
        return result

    # ── LAW 1 (fail-safe): safety-check failure suppresses NEW trades ─────────
    # When ANY safety/risk check below cannot be evaluated (raises), we cannot
    # confirm trading is safe. Per LAW 1 (fail-safe, not fail-open) the cycle
    # then HOLDS current positions (no new deployment/rebalance), records the
    # reason, sets status="blocked_safety_check_error", and fires a loud alert.
    # Holding (not forcing all-cash) avoids churn while still suppressing risk.
    _safety_failed = False
    _safety_reasons: list[str] = []

    def _mark_safety_failure(reason: str) -> None:
        """Record a LAW-1 fail-safe trigger (idempotent, never raises)."""
        nonlocal _safety_failed
        _safety_failed = True
        _safety_reasons.append(reason)
        notes.append(f"FAIL_SAFE_HOLD: {reason}")

    # ── Step 1b (MP-108): kill-switch check — override allocation if active ──
    # Deterministic. LAW 1: any exception → FAIL-SAFE (HOLD, suppress new trades,
    # alert), NOT fail-open. Kill-switch CANNOT be overridden (approved=False final).
    _ks_triggered = False
    _ks_reason = ""
    _ks_allocation: dict[str, float] = {}
    try:
        from spa_core.governance.kill_switch import run_kill_switch_check

        _ks_equity = (
            list(equity_doc.get("daily") or []) if isinstance(equity_doc, dict) else []
        )
        kill_status = run_kill_switch_check(equity_curve=_ks_equity, data_dir=ddir)
        _ks_triggered = bool(kill_status.get("triggered"))
        _ks_reason = str(kill_status.get("reason") or "")
        if _ks_triggered:
            _ks_allocation = dict(kill_status.get("allocation") or {})
            log.critical("KILL SWITCH ACTIVE: %s", _ks_reason)
            notes.append(f"kill_switch_active: {_ks_reason}")
    except Exception as exc:  # LAW 1: cannot confirm safe → HOLD, do NOT trade
        log.critical(
            "kill_switch check FAILED (%s) — FAIL-SAFE: holding positions, "
            "suppressing new trades", exc,
        )
        _mark_safety_failure(f"kill_switch_check_error: {type(exc).__name__}: {exc}")

    # ── Step 1c (ADR-034/048): SOFT-tier de-risk check — drawdown ∈ [5%, 10%) ──
    # Parallel to the HARD kill above. When the evidenced drawdown is in the soft
    # band the cycle must HALT new allocations / block any position INCREASE
    # (hold + reduce only) and emit an edge-triggered WARNING — it does NOT
    # liquidate. Mutually exclusive with the HARD kill (which already all-cashes).
    # Fail-safe: any error degrades to "no de-risk" (the HARD kill remains the
    # fail-closed safety authority for a real collapse).
    _derisk_active = False
    _derisk_reason = ""
    try:
        from spa_core.governance.kill_switch import run_derisk_check

        _derisk_equity = (
            list(equity_doc.get("daily") or []) if isinstance(equity_doc, dict) else []
        )
        _derisk_status = run_derisk_check(equity_curve=_derisk_equity, data_dir=ddir)
        _derisk_active = bool(_derisk_status.get("active"))
        _derisk_reason = str(_derisk_status.get("reason") or "")
        if _derisk_active:
            log.warning("SOFT DE-RISK ACTIVE: %s", _derisk_reason)
            notes.append(f"soft_derisk_active: {_derisk_reason}")
            # Edge-triggered WARNING via the existing alert path (no flood).
            if write and _derisk_status.get("should_alert"):
                try:
                    from spa_core.alerts.alert_manager import send_red_flag
                    send_red_flag([{
                        "protocol": "PORTFOLIO",
                        "severity": "WARN",
                        "category": "soft_derisk",
                        "message": f"Soft de-risk (drawdown 5–10%): {_derisk_reason}",
                        "source": "cycle_runner",
                    }])
                except Exception as _da_exc:  # noqa: BLE001
                    log.warning("soft de-risk alert dispatch failed (%s)", _da_exc)
    except Exception as _dexc:  # noqa: BLE001 — de-risk is advisory, never HALT
        log.warning(
            "soft de-risk check failed (%s) — continuing (hard kill is the "
            "fail-closed authority)", _dexc,
        )
        notes.append(f"soft_derisk_check_error: {type(_dexc).__name__}")

    # ── Step 2: allocator → target allocation ─────────────────────────────
    alloc = (allocator or _default_allocator(ddir)).allocate()
    target_usd = {
        str(p): float(v) for p, v in (getattr(alloc, "target_usd", {}) or {}).items()
    }
    model_used = getattr(alloc, "model_used", None)
    strategy_loop_active = bool(getattr(alloc, "strategy_loop_active", False))
    # WS1.1 (money-path data-integrity): provenance of the APY that drove the
    # allocator's ranking, surfaced per-position in current_positions.json so a
    # reviewer SEES which adapters were on live DeFiLlama data vs the stale
    # registry literal. Fail-safe: missing fields default to empty maps.
    _apy_sources_map: dict = dict(getattr(alloc, "apy_sources", {}) or {})
    _feed_coverage: dict = dict(getattr(alloc, "feed_coverage", {}) or {})
    _apy_as_of_map: dict = dict(_feed_coverage.get("as_of", {}) or {})
    _apy_used_map: dict = dict(getattr(alloc, "apy_used", {}) or {})
    if _feed_coverage:
        notes.append(
            "WS1.1 feed_coverage: {live}/{total} live, {stale} stale-fallback".format(
                live=_feed_coverage.get("live", 0),
                total=_feed_coverage.get("total", 0),
                stale=_feed_coverage.get("fallback_stale", 0),
            )
        )

    # ── ADR-033: strategy-loop activation mode (advisory, fail-safe) ──────────
    # Reads data/strategy_config.json and records the configured mode in the
    # cycle. In "shadow" mode (ADR-033 default) the tournament is evaluated and
    # logged but NEVER alters the real allocation. Only "active" mode lets a
    # confident shadow strategy steer it. Any error → degrade to "shadow"
    # without touching allocation; the cycle never fails on this.
    try:
        from spa_core.strategies.strategy_config import load_strategy_config
        _sl_cfg = load_strategy_config(data_dir=str(ddir))
        _sl_mode = _sl_cfg.get("strategy_loop_mode", "shadow")
        log.info(
            "ADR-033 strategy_loop_mode=%s (source=%s) | allocator strategy_loop_active=%s",
            _sl_mode, _sl_cfg.get("source"), strategy_loop_active,
        )
        notes.append(
            f"ADR-033 strategy_loop_mode={_sl_mode}"
            + (f" (active={strategy_loop_active})" if _sl_mode == "active" else " (advisory-only)")
        )
        # Safety invariant: in off/shadow the loop must NOT drive real allocation.
        if _sl_mode != "active" and strategy_loop_active:
            log.warning(
                "ADR-033: strategy_loop_active=True but mode=%s — forcing advisory-only",
                _sl_mode,
            )
            strategy_loop_active = False
            notes.append("ADR-033: shadow/off mode overrode active loop → advisory-only")
    except Exception as _sl_exc:  # never crash the cycle on config read
        log.warning("ADR-033 strategy_config read failed (%s) — advisory-only", _sl_exc)
        notes.append(f"ADR-033 strategy_config_error: {type(_sl_exc).__name__}")

    # MP-310: record allocation_proposal event (fail-safe)
    _audit_proposal_id: str | None = None
    try:
        from spa_core.audit.audit_trail import record_event as _audit_record
        _audit_ev = _audit_record(
            _correlation_id,
            "allocation_proposal",
            {
                "target_usd": {p: round(v, 2) for p, v in target_usd.items()},
                "model_used": model_used,
                "strategy_loop_active": strategy_loop_active,
            },
            data_dir=str(ddir),
        )
        _audit_proposal_id = _audit_ev.get("event_id")
    except Exception as _aexc:
        log.warning("audit allocation_proposal failed (%s)", _aexc)

    # ── Step 2a (MP-375): Daily Risk Limits gate — HALT blocks allocation ──
    # DL-01 daily loss, DL-02 peak drawdown: HALT → cycle exits with no trade.
    # DL-03 concentration, DL-04/05 APY sanity: WARN → noted, cycle continues.
    try:
        from spa_core.risk.daily_limits import DailyLimitsChecker
        _dl_checker = DailyLimitsChecker()
        _dl_eq_history = (
            list(equity_doc.get("daily") or []) if isinstance(equity_doc, dict) else []
        )
        # MP-AAVE-FIX: build the sanity map from adapters that returned a
        # *usable* live APY only. An adapter whose live feed is unavailable
        # reports status="error"/apy=None; coercing that to 0.0 and feeding it
        # to DL-04 produced a false "aave_v3 APY 0.00% below sanity floor
        # (stale data?)" warning every time the DeFiLlama feed blipped. A yield
        # we don't have cannot be sanity-checked, so such adapters are EXCLUDED
        # from the map (not zeroed). DL-04 still fires on a genuine live ~0% APY.
        _dl_apy_map = _sanity_apy_map(
            adapters if isinstance(adapters, list) else []
        )
        _dl_result = _dl_checker.check(_dl_eq_history, target_usd, _dl_apy_map)
        _dl_checker.save_result(_dl_result, ddir)
        # ── ADR-048 (DL-02 ⊂ HARD kill) reconciliation ────────────────────────
        # At ≥10% evidenced peak drawdown the AUTHORITATIVE response is the
        # hard-kill ALL-CASH (the stronger action), NOT DL-02's HOLD/HALT. DL-02
        # also HALTs at >10% peak drawdown and runs HERE (Step 2a), BEFORE the
        # kill-switch override (Step 2c) — so an un-reconciled DL-02 HALT would
        # early-return "blocked_by_daily_limits" (positions held, no all-cash)
        # and SHADOW the kill. Reconciliation (minimal, money-path order
        # preserved): when the hard kill is ARMED (_ks_triggered, computed in
        # Step 1b) we DEFER any DL-02-only HALT — we drop the DL-02 halt reason
        # so the cycle flows through to Step 2c where apply_kill_switch_override
        # forces all-cash. DL-01 (daily-loss) ALWAYS HALTs (it is a distinct axis
        # and is never deferred). If DL-01 is among the halt reasons the cycle
        # still HALTs as before.
        _dl_halt_reasons = list(_dl_result.get("halt_reasons") or [])
        if _dl_result["gate"] == "HALT" and _ks_triggered:
            _dl01_present = any("DL-01" in r for r in _dl_halt_reasons)
            _dl02_deferred = [r for r in _dl_halt_reasons if "DL-02" in r]
            if _dl02_deferred and not _dl01_present:
                # DL-02-only HALT while the hard kill is armed → defer to the
                # all-cash kill (stronger action wins). Do NOT early-return.
                log.critical(
                    "DAILY LIMITS DL-02 HALT DEFERRED to HARD kill (ADR-048): %s "
                    "→ cycle proceeds to all-cash kill-switch override",
                    "; ".join(_dl02_deferred),
                )
                notes.append(
                    "daily_limits_dl02_deferred_to_hard_kill (ADR-048): "
                    + "; ".join(_dl02_deferred)
                )
                _dl_result = dict(_dl_result)
                _dl_result["gate"] = "PASS"
                _dl_result["halt_reasons"] = []
        if _dl_result["gate"] == "HALT":
            log.critical(
                "DAILY LIMITS HALT: %s", "; ".join(_dl_result["halt_reasons"])
            )
            notes.append(
                "daily_limits_halt: " + "; ".join(_dl_result["halt_reasons"])
            )
            result = CycleResult(
                run_ts=run_ts,
                date=today,
                status="blocked_by_daily_limits",
                traded=False,
                trade_id=None,
                live_data=True,
                num_adapters_live=len(apy_map),
                current_equity=round(prev_equity, 2),
                daily_yield_usd=0.0,
                daily_return_pct=0.0,
                apy_today_pct=0.0,
                total_return_pct=round((prev_equity / capital_usd - 1.0) * 100.0, 4),
                days_running=_days_running(today, paper_start_date),
                model_used=model_used,
                strategy_loop_active=strategy_loop_active,
                positions=current_positions,
                notes=notes,
                policy_approved=False,
                correlation_id=_correlation_id,
                market_regime=_regime_name,
                regime_t1_avg_apy=_regime_t1_avg_apy,
            )
            _write_equity(ddir, equity_doc, prev_equity, today, 0.0, {}, 0.0)
            _write_status(ddir, result, paper_start_date, capital_usd, run_ts)
            return result
        if _dl_result["gate"] == "WARN":
            log.warning(
                "DAILY LIMITS WARN: %s", "; ".join(_dl_result["warn_reasons"])
            )
            for _w in _dl_result["warn_reasons"]:
                notes.append(f"daily_limits_warn: {_w}")
    except Exception as _dl_exc:
        log.warning("DailyLimitsChecker failed (%s) — fail-open, cycle continues", _dl_exc)
        notes.append(f"daily_limits_check_error: {type(_dl_exc).__name__}: {_dl_exc}")

    # ── Step 2b: Emergency Circuit Breakers (ADR-030) ────────────────────────
    # Runs AFTER DailyLimitsChecker, BEFORE RiskPolicy gate.
    # HALT or PAUSE aborts the cycle immediately — no trade, no equity accrual.
    # Fail-safe wrapper: the outer try catches any unexpected exception so a
    # broken breaker check never crashes the cycle (fail-open, WARNING only).
    if _emergency_breakers is not None and apy_map:
        try:
            _static_apy = {
                "aave_v3": 3.5, "compound_v3": 4.0, "morpho_blue": 4.8,
                "spark_susds": 4.6, "yearn_v3": 5.5, "euler_v2": 5.2,
                "maple": 6.5, "pendle": 8.5, "aave_v3_base": 3.8,
                "morpho_blue_base": 5.0, "extra_finance_base": 8.0,
            }
            _eb_equity_history = (
                list(equity_doc.get("daily") or [])
                if isinstance(equity_doc, dict)
                else []
            )
            _eb_result = _emergency_breakers.check_all(
                apy_map=apy_map,
                equity_history=_eb_equity_history,
                static_apy=_static_apy,
            )
            _atomic_write_json(ddir / "emergency_status.json", _eb_result)
            notes.append(
                f"emergency_breakers: status={_eb_result.get('status', 'UNKNOWN')} "
                f"triggered={_eb_result.get('triggered', [])}"
            )
            if _eb_result.get("status") in ("HALT", "PAUSE"):
                log.critical(
                    "EmergencyBreakers %s — triggered: %s",
                    _eb_result["status"],
                    _eb_result.get("triggered", []),
                )
                _eb_days = _days_running(today, paper_start_date)
                _eb_cycle_result = CycleResult(
                    run_ts=run_ts,
                    date=today,
                    status=f"blocked_by_emergency_{_eb_result['status'].lower()}",
                    traded=False,
                    trade_id=None,
                    live_data=True,
                    num_adapters_live=len(apy_map),
                    current_equity=round(prev_equity, 2),
                    daily_yield_usd=0.0,
                    daily_return_pct=0.0,
                    apy_today_pct=0.0,
                    total_return_pct=round((prev_equity / capital_usd - 1.0) * 100.0, 4),
                    days_running=_eb_days,
                    model_used=model_used,
                    strategy_loop_active=strategy_loop_active,
                    positions=current_positions,
                    notes=notes,
                    correlation_id=_correlation_id,
                    market_regime=_regime_name,
                    regime_t1_avg_apy=_regime_t1_avg_apy,
                )
                if write:
                    _write_status(ddir, _eb_cycle_result, paper_start_date, capital_usd, run_ts)
                return _eb_cycle_result
        except Exception as _eb_exc:  # LAW 1: cannot confirm safe → HOLD, no trade
            log.critical(
                "EmergencyBreakers check FAILED (%s) — FAIL-SAFE: holding positions, "
                "suppressing new trades", _eb_exc,
            )
            _mark_safety_failure(
                f"emergency_breakers_error: {type(_eb_exc).__name__}: {_eb_exc}"
            )

    # ── Step 2c-pre (ADR-031 / MP-1146): Analytics Blocking Gate ──────────────
    # Runs AFTER the allocator and BEFORE the RiskPolicy gate. Reads the Tier-A
    # blocking signals; any protocol flagged BLOCK has its target_usd zeroed and
    # the freed capital redistributed proportionally to the remaining (allowed)
    # protocols. Fail-open: any exception → WARNING + note, no blocking applied.
    apply_analytics_blocking_gate(
        target_usd,
        ddir=ddir,
        run_ts=run_ts,
        today=today,
        correlation_id=_correlation_id,
        write=write,
        notes=notes,
    )

    # ── Step 2b (MP-005): deterministic RiskPolicy gate before any trade ──
    gate = _apply_risk_policy_gate(target_usd, capital_usd, adapters, ddir=ddir)
    policy_checked = gate["error"] is None
    policy_blocked = False

    # MP-310: record risk_verdict event (fail-safe)
    _audit_verdict_id: str | None = None
    try:
        from spa_core.audit.audit_trail import record_event as _audit_record  # noqa: F811
        _audit_ev2 = _audit_record(
            _correlation_id,
            "risk_verdict",
            {
                "approved": gate.get("approved", True),
                "violations": list(gate.get("violations") or []),
                "warnings": list(gate.get("warnings") or []),
                "trimmed": gate.get("trimmed", False),
                "gate_error": gate.get("error"),
            },
            prev_event_id=_audit_proposal_id,
            data_dir=str(ddir),
        )
        _audit_verdict_id = _audit_ev2.get("event_id")
    except Exception as _aexc2:
        log.warning("audit risk_verdict failed (%s)", _aexc2)

    if gate["error"] is not None:
        # LAW 1: the RiskPolicy gate itself could not be evaluated. We cannot
        # confirm the target is safe → FAIL-SAFE: hold positions, suppress new
        # trades (do NOT skip the gate and trade anyway).
        log.critical(
            "RiskPolicy gate FAILED (%s) — FAIL-SAFE: holding positions, "
            "suppressing new trades", gate["error"],
        )
        _mark_safety_failure(f"risk_policy_gate_error: {gate['error']}")
    else:
        if gate["trimmed"]:
            target_usd = dict(gate["target_usd"])
            notes.append(
                "risk_policy: target trimmed to respect the min-cash buffer "
                f"(deployed capped at ${sum(target_usd.values()):,.0f})."
            )
        if not gate["approved"]:
            policy_blocked = True
            log.warning(
                "Allocation blocked by RiskPolicy: %s", "; ".join(gate["violations"])
            )
            notes.append(
                "blocked_by_policy: " + "; ".join(gate["violations"])
            )
            if write:
                _record_policy_block(
                    ddir,
                    run_ts=run_ts,
                    date=today,
                    gate=gate,
                    current_positions=current_positions,
                    capital_usd=capital_usd,
                )

    # ── Step 2c (MP-108): kill-switch override — force all-cash allocation ──
    target_usd = apply_kill_switch_override(
        target_usd,
        ks_triggered=_ks_triggered,
        ks_allocation=_ks_allocation,
        capital_usd=capital_usd,
        notes=notes,
    )

    # ── Step 2c-soft (ADR-034/048): SOFT de-risk gate — halt new/increase ─────
    # Drawdown ∈ [5%, 10%): cap every protocol's target to its currently-held
    # USD (no NEW positions, no INCREASES; hold + reduce stay allowed). Mutually
    # exclusive with the HARD kill above (_derisk_active is False when killed),
    # so this never fights the all-cash override.
    target_usd = apply_soft_derisk_gate(
        target_usd,
        current_positions=current_positions,
        derisk_active=_derisk_active,
        notes=notes,
    )

    # ── Step 2d (ADR-025): Base chain gas kill-switch — zero Base allocations ──
    apply_base_gas_kill_switch(
        target_usd,
        ddir=ddir,
        base_gas_monitor_class=_BASE_GAS_MONITOR_CLASS,
        base_chain_monitoring=_BASE_CHAIN_MONITORING,
        notes=notes,
    )

    # ── ALLOC-002 (oscillation fix): collapse the raw allocator target to a
    # policy-compliant ≤8-protocol book BEFORE the rebalance diff. The diff,
    # the recorded trade, and effective_positions all use this compliant target
    # so consecutive cycles on unchanged market data converge (near-zero
    # turnover) instead of churning 24↔8 every cycle. Deterministic + fail-open.
    # Skipped under fail-safe HOLD / policy-block (we are holding regardless).
    _alloc002_pre_collapsed = False
    if not _safety_failed and not policy_blocked:
        target_usd, _alloc002_pre_collapsed = _compliant_target(
            target_usd, capital_usd, ddir, write
        )
        if _alloc002_pre_collapsed:
            notes.append(
                "ALLOC-002: raw allocator target ({} protocols) collapsed to "
                "compliant book ({} protocols) before rebalance diff.".format(
                    len(target_usd), len(target_usd)
                )
            )
            # ── ADR-034 (D1-T1 fix): RE-APPLY the soft de-risk cap AFTER the
            # ALLOC-002 collapse. _compliant_target redistributes freed capital
            # across the survivor book (rebalancer / safe-fallback) and can
            # RE-GROW a protocol above its held size — or re-open an un-held one —
            # silently UNDOING the soft "no-new / no-increase" guarantee the
            # earlier gate established. Re-clamping here makes the composition
            # cap-preserving: held positions can only be held or reduced, never
            # grown, and no new protocol can be opened while in [5%,10%) drawdown.
            # Idempotent + no-op when _derisk_active is False (non-derisk path
            # unchanged). The freed capital implicitly stays in cash.
            target_usd = apply_soft_derisk_gate(
                target_usd,
                current_positions=current_positions,
                derisk_active=_derisk_active,
                notes=notes,
            )

    # ── Step 2e (RTMR / ADR-053): honor the emergency-path risk posture ────────
    # The RTMR sense/emergency service writes data/monitoring/risk_posture.json on a
    # de-risk; the rebalance-loop must respect any active FREEZE/CAP/EXIT/DEFENSIVE (§7).
    # De-risk-only (can only REDUCE a target; freed capital stays in cash) and a NO-OP
    # when the posture is NORMAL / unreadable — so on a healthy market this changes
    # nothing. Applied LAST, on the final compliant book, so it clamps the actual targets.
    target_usd = apply_rtmr_posture_gate(
        target_usd,
        capital_usd=capital_usd,
        now_ts=int(datetime.now(timezone.utc).timestamp()),
        notes=notes,
    )

    # ── Step 3: virtual rebalance trade if allocation moved > threshold ───
    trades: list[dict] = _read_json(ddir / TRADES_FILENAME, [])
    if not isinstance(trades, list):
        trades = []
    diff_usd = _allocation_diff_usd(current_positions, target_usd)
    threshold_usd = trade_threshold_pct * capital_usd
    # LAW 1 (fail-safe): if a safety check could not be evaluated, suppress ALL
    # new deployment/rebalancing this cycle — hold current positions. This takes
    # priority over the normal trade decision and over policy_blocked.
    traded = (not _safety_failed) and (not policy_blocked) and diff_usd > threshold_usd
    trade_id: str | None = None

    if _safety_failed:
        # HOLD: keep prior positions verbatim, deploy nothing new. A loud alert
        # was logged at .critical above; fire the Telegram alarm here too.
        effective_positions = dict(current_positions)
        _safety_reason_str = "; ".join(_safety_reasons)
        notes.append(
            "FAIL_SAFE_HOLD: safety check could not be evaluated — held current "
            f"positions, no new trades ({_safety_reason_str})."
        )
        if write:
            _send_safety_failsafe_alert(_safety_reason_str, _correlation_id)
        # MP-310: record trade_blocked (fail-safe, advisory)
        try:
            from spa_core.audit.audit_trail import record_event as _audit_record  # noqa: F811
            _audit_record(
                _correlation_id,
                "trade_blocked",
                {"reason": "safety_check_error", "detail": _safety_reasons},
                prev_event_id=_audit_verdict_id,
                data_dir=str(ddir),
            )
        except Exception as _aexc_sf:  # noqa: BLE001
            log.warning("audit safety-hold trade_blocked failed (%s)", _aexc_sf)
    elif traded:
        trade_id = _next_trade_id(trades)
        trades.append(
            {
                "trade_id": trade_id,
                "ts": run_ts,
                "type": "rebalance",
                "from_allocation": {p: round(v, 2) for p, v in current_positions.items()},
                # ALLOC-002: target_usd here is the COMPLIANT (count-capped ≤8)
                # book — same object the diff & effective_positions use — so the
                # recorded to_allocation matches what is actually held.
                "to_allocation": {p: round(v, 2) for p, v in target_usd.items()},
                "diff_usd": round(diff_usd, 2),
                # Real rebalance turnover in USD: one-sided gross capital actually
                # relocated this cycle (L1 distance / 2 — each dollar leaving pool
                # A and entering pool B is counted once, not twice). Used downstream
                # to estimate transaction cost / slippage. ~0 on a stable cycle
                # (no phantom churn after ALLOC-002), >0 on a real rebalance.
                "delta_abs": round(diff_usd / 2.0, 2),
                "reason": "orchestrator_cycle",
                "model_used": model_used,
                "strategy_loop_active": strategy_loop_active,
                "capital": capital_usd,
                "is_demo": False,
            }
        )
        trades = trades[-MAX_TRADES:]  # ring-buffer
        effective_positions = dict(target_usd)
        notes.append(
            f"rebalance {trade_id}: |Δ|=${diff_usd:,.0f} > "
            f"${threshold_usd:,.0f} threshold."
        )
        # MP-310: record trade_executed (fail-safe)
        try:
            from spa_core.audit.audit_trail import record_event as _audit_record  # noqa: F811
            _audit_record(
                _correlation_id,
                "trade_executed",
                {
                    "trade_id": trade_id,
                    "diff_usd": round(diff_usd, 2),
                    "delta_abs": round(diff_usd / 2.0, 2),
                    "from_allocation": {p: round(v, 2) for p, v in current_positions.items()},
                    "to_allocation": {p: round(v, 2) for p, v in target_usd.items()},
                },
                prev_event_id=_audit_verdict_id,
                data_dir=str(ddir),
            )
        except Exception as _aexc3:
            log.warning("audit trade_executed failed (%s)", _aexc3)
    elif policy_blocked:
        # Blocked rebalance: hold the previous positions; a first-ever cycle
        # that is blocked deploys nothing (the gate prevented the entry).
        effective_positions = dict(current_positions)
        # MP-310: record trade_blocked (fail-safe)
        try:
            from spa_core.audit.audit_trail import record_event as _audit_record  # noqa: F811
            _audit_record(
                _correlation_id,
                "trade_blocked",
                {
                    "violations": list(gate.get("violations") or []),
                    "diff_usd": round(diff_usd, 2),
                },
                prev_event_id=_audit_verdict_id,
                data_dir=str(ddir),
            )
        except Exception as _aexc4:
            log.warning("audit trade_blocked failed (%s)", _aexc4)
    else:
        effective_positions = dict(current_positions) if current_positions else dict(target_usd)
        notes.append(
            f"no rebalance: |Δ|=${diff_usd:,.0f} ≤ ${threshold_usd:,.0f} threshold."
        )

    # ── ALLOC-002: enforce protocol-count / T1 floor on the FINAL allocation ──
    # The StrategyAllocator + RiskPolicy gate (policy.py) cap per-protocol
    # concentration but NOT the protocol *count* nor the T1 floor. ALLOC-001 only
    # validated the INCOMING positions, so an over-diversified target (e.g. 23
    # protocols) could be persisted unchecked and rules_watchdog would flag it.
    # Here we validate the OUTGOING book against policy_enforcer and, on
    # violation, adopt the rebalancer's guaranteed-compliant allocation. Fail-open.
    # LAW 1: skip when a safety check failed — we are holding and must not let the
    # rebalancer deploy new positions while a safety check is unverifiable.
    if write and effective_positions and not _safety_failed:
        try:
            from spa_core.risk.policy_enforcer import validate_positions as _pe_final
            _eff_cash = capital_usd - sum(effective_positions.values())
            _fin_check = _pe_final(
                positions=effective_positions,
                capital_usd=capital_usd,
                cash_usd=_eff_cash,
            )
            if not _fin_check.passed:
                _fin_rules = [v.rule for v in _fin_check.violations]
                log.warning(
                    "ALLOC-002: final allocation violates enforcer (%s) — "
                    "adopting rebalancer fallback", _fin_rules,
                )
                from spa_core.tuner.portfolio_rebalancer import rebalance_portfolio as _rb2
                if _rb2(capital_usd=capital_usd, data_dir=ddir, write=True, send_alert=False):
                    _rb_pos = (
                        _read_json(ddir / POSITIONS_FILENAME, {}).get("positions", {}) or {}
                    )
                    if _rb_pos:
                        effective_positions = {p: float(v) for p, v in _rb_pos.items()}
                        notes.append(
                            "ALLOC-002: enforcer violation {} — rebalanced to {} protocols".format(
                                _fin_rules, len(effective_positions)
                            )
                        )
                else:
                    notes.append(
                        "ALLOC-002: enforcer violation {} but rebalancer rejected — kept book".format(
                            _fin_rules
                        )
                    )
        except Exception as _alloc002_exc:  # noqa: BLE001
            log.warning("ALLOC-002: enforcement skipped (%s)", _alloc002_exc)
            notes.append("ALLOC-002: enforcement_error: {}".format(type(_alloc002_exc).__name__))

    # ── Step 4 + 5: accrue yield & upsert today's equity bar ──────────────
    deployed = sum(effective_positions.values())
    # apy_today = realised portfolio APY on a total-equity basis (cash drags).
    weighted_apy = (
        sum(usd * apy_map.get(p, 0.0) for p, usd in effective_positions.items())
        / prev_equity
        if prev_equity
        else 0.0
    )
    equity_doc = equity_doc if isinstance(equity_doc, dict) else {}
    # N3(b): the day is "fallback"-accrued if there was no live feed at all, or
    # if any DEPLOYED position drew its APY from a fallback file rather than live.
    _accrual_source = (
        "fallback"
        if (not live or any(p in _fallback_apy_pools for p in effective_positions))
        else "live"
    )
    equity_doc, close_equity, daily_yield, daily_return_pct = _upsert_equity_point(
        equity_doc,
        date=today,
        apy_today_pct=weighted_apy,
        positions=effective_positions,
        apy_map=apy_map,
        run_ts=run_ts,
        accrual_source=_accrual_source,
    )

    days = _days_running(today, paper_start_date)
    # LAW 1: a failed safety check is the most safety-critical signal — it takes
    # priority in the reported status. MP-108: kill-switch next, then policy.
    _cycle_status = (
        "blocked_safety_check_error" if _safety_failed
        else "kill_switch" if _ks_triggered
        else ("blocked_by_policy" if policy_blocked else "ok")
    )
    result = CycleResult(
        run_ts=run_ts,
        date=today,
        status=_cycle_status,
        traded=traded,
        trade_id=trade_id,
        live_data=True,
        num_adapters_live=len(apy_map),
        current_equity=round(close_equity, 2),
        daily_yield_usd=round(daily_yield, 4),
        daily_return_pct=daily_return_pct,
        apy_today_pct=round(weighted_apy, 4),
        total_return_pct=round((close_equity / capital_usd - 1.0) * 100.0, 4),
        days_running=days,
        model_used=model_used,
        strategy_loop_active=strategy_loop_active,
        positions=effective_positions,
        notes=notes,
        policy_checked=policy_checked,
        policy_approved=not policy_blocked,
        policy_trimmed=bool(gate["trimmed"]) if policy_checked else False,
        policy_violations=list(gate.get("violations") or []),
        policy_warnings=list(gate.get("warnings") or []),
        kill_switch_active=_ks_triggered,
        kill_switch_reason=_ks_reason,
        safety_check_failed=_safety_failed,
        safety_check_reason="; ".join(_safety_reasons),
        correlation_id=_correlation_id,
        market_regime=_regime_name,
        regime_t1_avg_apy=_regime_t1_avg_apy,
    )

    # ── Step 6: persist everything atomically ─────────────────────────────
    if write:
        _atomic_write_json(ddir / TRADES_FILENAME, trades)
        _atomic_write_json(ddir / EQUITY_FILENAME, equity_doc)
        # WS1.1 TRACK-CONTINUITY SELF-HEAL: the append above only writes TODAY's
        # bar onto the last bar — it can't recover a day that a real cycle already
        # ran but whose bar was later dropped (e.g. a git reset to a stale
        # committed equity curve clobbered the 2026-06-27/28/29 bars). After every
        # live persist we detect any day that has GROUND-TRUTH cycle-log evidence
        # but no evidenced bar, and recover it fail-CLOSED from the log (never
        # fabricating a day without evidence). Idempotent: no gap → no-op. Wrapped
        # so a heal failure can NEVER break the cycle's own write.
        try:
            from spa_core.paper_trading.track_self_heal import heal_track as _heal_track
            # Logs live as a SIBLING of the data dir (repo: data/ ↔ logs/). Deriving
            # from ``ddir`` keeps test/sandbox runs hermetic — a tmp data dir has no
            # logs/ sibling, so the heal is a strict no-op there and can never pull
            # the real repo track into a sandbox curve.
            _heal_logs = ddir.parent / "logs"
            _heal_rep = _heal_track(
                equity_path=ddir / EQUITY_FILENAME,
                logs_dir=_heal_logs,
                apply=True,
            )
            if _heal_rep.get("healed") or _heal_rep.get("repaired"):
                log.info(
                    "WS1.1 self-heal: recovered %s + repaired %s "
                    "(evidenced %s → %s)",
                    _heal_rep.get("healed"), _heal_rep.get("repaired"),
                    _heal_rep.get("evidenced_before"),
                    _heal_rep.get("evidenced_after"),
                )
                notes.append(
                    "WS1.1 self-heal: recovered {} evidenced day(s), "
                    "repaired {} base-drift day(s)".format(
                        len(_heal_rep.get("healed") or []),
                        len(_heal_rep.get("repaired") or []),
                    )
                )
                # Re-read the healed doc so the rest of the cycle (status, summary
                # readers) sees the recovered bars, not the pre-heal in-memory doc.
                _healed_doc = _read_json(ddir / EQUITY_FILENAME, None)
                if isinstance(_healed_doc, dict) and _healed_doc.get("daily"):
                    equity_doc = _healed_doc
        except Exception as _heal_exc:  # noqa: BLE001 — heal is best-effort
            log.warning("WS1.1 self-heal skipped (non-fatal): %s", _heal_exc)
        # Compliance / tier / APY summary — downstream readers (SYSTEM_BRIEFING,
        # dashboard) display these fields; the rebalancer writes them too, so the
        # cycle's own write must include them or it clobbers the rich doc with a
        # thin one (→ false "NOT compliant / 0% APY / T1 0%" in the briefing).
        _cash_usd = capital_usd - deployed
        try:
            from spa_core.risk.policy_enforcer import T1_ADAPTERS as _T1
            _t1_usd = sum(v for p, v in effective_positions.items() if p in _T1)
        except Exception:  # noqa: BLE001
            _t1_usd = 0.0
        # Percentages are allocation RATIOS (scale-invariant) — computed on the cost basis.
        _t1_pct = round(_t1_usd / capital_usd * 100.0, 2) if capital_usd else 0.0
        _t2_pct = round((deployed - _t1_usd) / capital_usd * 100.0, 2) if capital_usd else 0.0
        _cash_pct = round(_cash_usd / capital_usd * 100.0, 2) if capital_usd else 0.0
        _deployed_apy = round(
            sum(v * apy_map.get(p, 0.0) for p, v in effective_positions.items()) / deployed,
            4,
        ) if deployed else 0.0
        # NAV RECONCILIATION: positions/cash are stored at COST BASIS (sized on capital_usd,
        # stable so held positions don't re-mark/compound across cycles). The book's accrued
        # yield lives in current_equity; expose it as an explicit component so that
        #   deployed + cash + accrued_yield == current_equity  (proof-of-reserves reconciles).
        _equity = float(getattr(result, "current_equity", 0.0) or 0.0) or capital_usd
        _accrued_yield = round(_equity - capital_usd, 2)
        # WS1.1: per-position APY provenance. Each deployed position carries
        # ``apy_source`` ("live" | "fallback_stale"), the apy_pct actually used,
        # and ``as_of`` — so a reviewer SEES which book lines ranked on live
        # DeFiLlama data vs the stale registry literal. A position that was
        # accrued from a registry fallback (P0-B1 path) but for which the
        # allocator has no provenance is conservatively stamped "fallback_stale".
        def _pos_apy_source(p: str) -> str:
            src = _apy_sources_map.get(p)
            if src in ("live", "fallback_stale"):
                return src
            return "fallback_stale" if p in _fallback_apy_pools else "unknown"

        _positions_detail = {
            p: {
                "usd": round(v, 2),
                "apy_source": _pos_apy_source(p),
                "apy_pct": round(float(_apy_used_map.get(p, apy_map.get(p, 0.0))), 4),
                "as_of": _apy_as_of_map.get(p, run_ts),
            }
            for p, v in effective_positions.items()
        }
        _atomic_write_json(
            ddir / POSITIONS_FILENAME,
            {
                "generated_at": run_ts,
                "source": "cycle_runner",
                "execution_mode": "read_only_simulation",
                "is_demo": False,
                "capital_usd": capital_usd,
                "current_equity_usd": round(_equity, 2),
                "deployed_usd": round(deployed, 2),
                "cash_usd": round(_cash_usd, 2),
                "accrued_yield_usd": _accrued_yield,
                "model_used": model_used,
                "policy_compliant": bool(result.policy_approved),
                "policy_version": "v1.0",
                "tuner_expected_apy": _deployed_apy,
                # WS1.1: cycle-level feed coverage (live vs stale-fallback counts).
                "feed_coverage": _feed_coverage,
                # WS1.1: per-position provenance (apy_source / apy_pct / as_of).
                "positions_detail": _positions_detail,
                "positions": {p: round(v, 2) for p, v in effective_positions.items()},
                "validation_summary": {
                    "capital_usd": capital_usd,
                    "current_equity_usd": round(_equity, 2),
                    "deployed_usd": round(deployed, 2),
                    "cash_usd": round(_cash_usd, 2),
                    "accrued_yield_usd": _accrued_yield,
                    "protocol_count": len(effective_positions),
                    "t1_pct": _t1_pct,
                    "t2_pct": _t2_pct,
                    "cash_pct": _cash_pct,
                },
            },
        )
        _write_status(ddir, result, paper_start_date, capital_usd, run_ts)

        # ── Post-cycle advisory / analytics / shadow / reporting tail ──────
        # Extracted verbatim to cycle_reporting.run_post_cycle_advisory (N12).
        # All sub-blocks are independently fail-safe; ``notes`` is passed by
        # reference so in-place appends still reach the returned result.
        run_post_cycle_advisory(
            ddir=ddir,
            result=result,
            apy_map=apy_map,
            adapters=adapters,
            effective_positions=effective_positions,
            close_equity=close_equity,
            equity_doc=equity_doc,
            now_dt=now_dt,
            today=today,
            run_ts=run_ts,
            track_persister_fn=track_persister_fn,
            notes=notes,
        )

    return result


# The reporting / monitor / status tail (_run_daily_monitors,
# _should_send_alert, _run_cycle_alerts, _last_trade_id_from_file,
# _write_status, save_dashboard_snapshot, _save_cycle_snapshot_safe) now lives
# in ``spa_core/paper_trading/cycle_reporting.py`` (N12 decomposition) and is
# re-imported at the top of this module for back-compat.


# ─── CLI ──────────────────────────────────────────────────────────────────────


def _print_report(result: CycleResult) -> None:
    r = result
    print("─" * 64)
    print(f"SPA paper-trading cycle  [{r.date}]  status={r.status}")
    print("─" * 64)
    print(f"  live adapters     : {r.num_adapters_live}")
    print(f"  model             : {r.model_used}  (strategy_loop={r.strategy_loop_active})")
    print(f"  traded            : {r.traded}  (trade_id={r.trade_id})")
    policy = "skipped" if not r.policy_checked else (
        "approved" if r.policy_approved else "BLOCKED"
    )
    print(f"  risk policy gate  : {policy}"
          + (f"  ({len(r.policy_violations)} violations)" if r.policy_violations else ""))
    print(f"  daily yield       : ${r.daily_yield_usd:,.4f}")
    print(f"  apy today         : {r.apy_today_pct:.4f}%")
    print(f"  equity            : ${r.current_equity:,.2f}")
    print(f"  total return      : {r.total_return_pct:.4f}%")
    print(f"  days running      : {r.days_running}")
    if r.positions:
        print("  positions:")
        for p, v in sorted(r.positions.items(), key=lambda kv: -kv[1]):
            print(f"      {p:<16} ${v:,.2f}")
    for n in r.notes:
        print(f"  • {n}")
    print("─" * 64)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cycle_runner",
        description="Run one real paper-trading cycle (read-only, paper only).",
    )
    parser.add_argument("--dry-run", action="store_true", help="compute but write nothing")
    parser.add_argument("--verbose", action="store_true", help="verbose per-step output")
    parser.add_argument("--data-dir", default=None, help="override data directory")
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "WRITE-INTERLOCK opt-in: permit writing the CANONICAL live track at "
            "<repo>/data. Default (no flag) is fail-CLOSED — writes are "
            "redirected to a sandbox so a stray dev-shell run never corrupts the "
            "honest go-live track. Equivalent env: SPA_ALLOW_LIVE_WRITE=1. The "
            "production launchd agent MUST pass this flag."
        ),
    )
    parser.add_argument(
        "--no-monitors",
        action="store_true",
        help="skip the MP-107 external monitors (red flags / governance / incidents)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    # Resolve the effective data dir ONCE under the write-interlock so that the
    # cycle AND all post-cycle steps (monitors / alerts / analytics / smart
    # modules below, which take ``data_dir``) write to the SAME place. Without
    # this, a default (no --live) run would still let those post-steps mutate
    # the canonical dir. Fail-CLOSED: no opt-in ⇒ sandbox.
    _allow_live = bool(args.live)
    _eff_dir, _redirected = resolve_data_dir(args.data_dir, allow_live_write=_allow_live)
    if _redirected:
        print(
            "(write-interlock: no --live / SPA_ALLOW_LIVE_WRITE=1 — canonical "
            f"track NOT written; sandbox = {_eff_dir})"
        )
    # Downstream steps key off this effective dir (string for back-compat APIs).
    _eff_data_dir = str(_eff_dir)

    result = run_cycle(
        data_dir=args.data_dir, write=not args.dry_run, allow_live_write=_allow_live
    )
    _print_report(result)

    # MP-109: backup spa.db after each real cycle run.
    if not args.dry_run:
        try:
            from spa_core.persistence.db import create_daily_backup, cleanup_old_backups
            backup_path = create_daily_backup()
            cleanup_old_backups(keep_days=30)
            logging.info("DB backup: %s", backup_path)
        except Exception as _e:
            logging.warning("Backup failed: %s", _e)

    # MP-107: refresh external-signal snapshots once per daily run (fail-safe;
    # network-bound, hence here in the CLI and not inside run_cycle()).
    if not args.dry_run and not args.no_monitors:
        monitors = _run_daily_monitors(_eff_data_dir)
        for name, status in monitors.items():
            print(f"  monitor {name:<12}: {status}")

    # MP-016: Telegram alerts after the cycle & monitors (fail-safe;
    # network-bound, hence here in the CLI and not inside run_cycle()).
    if not args.dry_run:
        alerts = _run_cycle_alerts(_eff_data_dir, date=result.date)
        for name, ok in alerts.items():
            print(f"  alert   {name:<12}: {'sent' if ok else 'FAILED'}")

    # MP-016b: periodic reports — weekly (Monday) and monthly (1st of month).
    if not args.dry_run:
        try:
            from spa_core.alerts import alert_manager as _am
            if datetime.now().weekday() == 0:   # Monday
                ok_w = _am.send_weekly_report()
                print(f"  alert   {'weekly':<12}: {'sent' if ok_w else 'FAILED'}")
            if datetime.now().day == 1:          # 1st of month
                ok_m = _am.send_monthly_report()
                print(f"  alert   {'monthly':<12}: {'sent' if ok_m else 'FAILED'}")
        except Exception as _exc:               # noqa: BLE001 — never crash the cycle
            log.warning("periodic alerts failed (%s) — cycle continues", _exc)

    # MP-103: generate investor PDF report after the full cycle (fail-safe;
    # reportlab is an optional dependency — a missing install or any rendering
    # error must never fail the daily cycle).
    if not args.dry_run:
        try:
            from spa_core.reporting.pdf_report import generate_pdf_report
            pdf_path = generate_pdf_report(data_dir=_eff_data_dir)
            logging.info("PDF report generated: %s", pdf_path)
            print(f"  pdf report  : {pdf_path}")
        except Exception as _pdf_exc:  # noqa: BLE001
            logging.warning("PDF generation failed (%s) — cycle continues", _pdf_exc)

    # MP-207: Allocation Tuner — запускать по воскресеньям (weekday==6).
    # Сохраняет предложение в data/tuner_suggestion.json, НЕ применяет
    # автоматически — только логирует. LLM_FORBIDDEN не нарушается:
    # тюнер — детерминированный grid search без LLM-вызовов.
    if not args.dry_run and datetime.now().weekday() == 6:  # Sunday
        try:
            from spa_core.tuner.allocation_tuner import run_allocation_tuner
            _suggestion = run_allocation_tuner(data_dir=_eff_data_dir)
            log.info(
                "MP-207 Tuner suggestion: expected APY %.2f%%, Sharpe %.3f, "
                "improvements: %s",
                _suggestion.expected_apy,
                _suggestion.expected_sharpe,
                _suggestion.improvements,
            )
            print(
                f"  tuner       : APY {_suggestion.expected_apy:.2f}%"
                f" Sharpe {_suggestion.expected_sharpe:.3f}"
                f" (saved tuner_suggestion.json)"
            )
        except Exception as _tuner_exc:  # noqa: BLE001 — never crash the cycle
            log.warning("MP-207 Tuner failed (%s) — cycle continues", _tuner_exc)

    # MP-663: Run unified analytics pipeline after each cycle (fail-safe;
    # purely advisory — never modifies allocator / risk / execution state).
    if not args.dry_run:
        _run_analytics_pipeline(data_dir=_eff_data_dir)

    # WS2.1 + WS2.2: refresh the day-30 fundability pack (forward-analytics
    # scorecard → docs/FUNDABILITY.md) after each cycle. Advisory / read-only.
    # GUARDRAIL: skipped on a sandbox-redirected run (no --live) — docs/FUNDABILITY.md
    # is a canonical artifact and must never be regenerated from sandbox data.
    if not args.dry_run and not _redirected:
        _run_fundability_pack(data_dir=_eff_data_dir)
    elif not args.dry_run and _redirected:
        print("  fundability : skipped (sandbox run — canonical doc not regenerated)")

    # MP-1576..1580: smart / autonomous advisory modules after each cycle.
    # All STRICTLY read-only / advisory; each is independently fail-safe and
    # never modifies allocator / risk / execution state or touches capital.
    if not args.dry_run:
        _run_smart_modules(data_dir=_eff_data_dir, send_telegram=not args.no_monitors)

    if args.dry_run:
        print("(dry-run: no files written)")
    return 0 if result.status == "ok" else 1


def _run_smart_modules(data_dir=None, send_telegram: bool = True) -> None:
    """Run the MP-1576..1580 advisory modules post-cycle (each fail-safe).

    Order: adaptive cadence → smart rebalance signal → anomaly scan →
    KANBAN metrics → daily performance summary. A failure in any one module
    is logged and never aborts the cycle or the remaining modules.
    """
    from pathlib import Path as _Path
    ddir = _Path(data_dir) if data_dir else None

    # 1. Adaptive cycle-frequency recommendation (MP-1576).
    try:
        from spa_core.paper_trading.adaptive_scheduler import run as _adaptive_run
        dec = _adaptive_run(data_dir=ddir, write=True)
        print(f"  adaptive    : {dec.mode} ({dec.interval_minutes}min)")
    except Exception as _e:  # noqa: BLE001
        log.warning("MP-1576 adaptive_scheduler failed (non-critical): %s", _e)

    # 2. Smart rebalance trigger signal (MP-1577).
    try:
        from spa_core.paper_trading.rebalance_trigger import evaluate_from_state
        _data_path = str(ddir) if ddir else "data"
        verdict = evaluate_from_state(_data_path)
        from spa_core.utils.atomic import atomic_save as _atomic_save
        _atomic_save(verdict, str(_Path(_data_path) / "rebalance_trigger.json"))
        print(f"  rebalance?  : {verdict.get('should_rebalance')} "
              f"{verdict.get('triggered') or ''}")
    except Exception as _e:  # noqa: BLE001
        log.warning("MP-1577 rebalance_trigger failed (non-critical): %s", _e)

    # 3. Anomaly detection + alerts (MP-1579).
    try:
        from spa_core.monitoring.anomaly_detector import AnomalyDetector
        det = AnomalyDetector(data_dir=ddir)
        out = det.run(alert=send_telegram, write=True)
        print(f"  anomalies   : {out['count']} detected, "
              f"{out.get('telegram_sent', 0)} alerted")
    except Exception as _e:  # noqa: BLE001
        log.warning("MP-1579 anomaly_detector failed (non-critical): %s", _e)

    # 4. KANBAN completion metrics (MP-1580).
    try:
        from spa_core.reporting.kanban_metrics import run as _kanban_run
        m = _kanban_run(write=True)
        print(f"  kanban      : {m['done']}/{m['total']} ({m['completion_pct']:.1f}%)")
    except Exception as _e:  # noqa: BLE001
        log.warning("MP-1580 kanban_metrics failed (non-critical): %s", _e)

    # 5. Daily performance summary + Telegram (MP-1578).
    try:
        from spa_core.agents.daily_summary_agent import DailySummaryAgent
        agent = DailySummaryAgent(data_dir=ddir)
        res = agent.run(send=send_telegram, write=True)
        print(f"  summary     : day {res.get('day_N')} "
              f"(telegram_sent={res.get('telegram_sent')})")
    except Exception as _e:  # noqa: BLE001
        log.warning("MP-1578 daily_summary_agent failed (non-critical): %s", _e)

    # 6. T2 aggregate concentration early-warning (MP-1263).
    #    Advisory only — RiskPolicy still enforces the hard 50% ADR-019 cap.
    #    Tiered alerts: 42% advisory (log) → 45% WARNING (Telegram) →
    #    50% BREACH. Fail-safe: never aborts the cycle.
    try:
        from spa_core.risk.concentration_monitor import T2ConcentrationAlert
        t2 = T2ConcentrationAlert(data_dir=ddir)
        rep = t2.run(data_dir=ddir, send_telegram=send_telegram, write=True)
        print(f"  t2_conc     : {rep['status']} "
              f"{rep['t2_total_pct']:.2f}% (headroom {rep['headroom_pct']:.2f}%, "
              f"telegram_sent={rep['telegram_sent']})")
    except Exception as _e:  # noqa: BLE001
        log.warning("MP-1263 T2 concentration monitor failed (non-critical): %s", _e)


def _run_analytics_pipeline(data_dir: "str | os.PathLike | None" = None) -> None:
    """Run analytics pipeline post-cycle. Non-blocking — failures are logged."""
    try:
        from spa_core.analytics.analytics_pipeline import AnalyticsPipeline
        from pathlib import Path as _Path
        pipeline = AnalyticsPipeline(
            data_dir=_Path(data_dir) if data_dir else None
        )
        report = pipeline.run()
        log.info(
            "MP-663 Analytics pipeline: %d modules OK, %d failed",
            report["modules_run"],
            report["modules_failed"],
        )
        print(
            f"  analytics   : {report['modules_run']} modules OK,"
            f" {report['modules_failed']} failed"
            f" ({report['elapsed_sec']:.2f}s)"
        )
    except Exception as _ap_exc:  # noqa: BLE001 — never crash the cycle
        log.warning("MP-663 Analytics pipeline failed (non-critical): %s", _ap_exc)


def _run_fundability_pack(data_dir: "str | os.PathLike | None" = None) -> None:
    """Day-30 fundability artifacts — refreshed every (live) cycle.

    WS2.1 + WS2.2 (Yield Capture run). Two ordered steps, both advisory /
    read-only and INDEPENDENTLY fail-safe (a failure is logged and never aborts
    the cycle):

      2.1  ``forward_analytics.build_scorecard(write=True)`` — recompute the
           risk-adjusted scorecard ON the accruing forward series (computed
           STRICTLY on each track's evidenced bars via track_integrity, honest
           THIN/UNKNOWN until ~day 20) → ``<data_dir>/forward_analytics.json``.
      2.2  ``generate_fundability_onepager`` (--md equivalent) — regenerate
           ``docs/FUNDABILITY.md`` AFTER 2.1 so the pack sources the fresh
           scorecard. The one-pager is the no-unsourced-number guard: every
           figure is sourced live from ``data/`` or printed as data-unavailable.

    GUARDRAIL (write-interlock): this runs only against the CANONICAL data dir.
    ``docs/FUNDABILITY.md`` is a canonical artifact that reads ``<root>/data``,
    so the caller MUST skip this step on a sandbox-redirected run (no --live) —
    otherwise the canonical doc would be regenerated from sandbox data. The
    caller gates this on ``not _redirected``; the scorecard is still scoped to
    ``data_dir`` for defence in depth.
    """
    from pathlib import Path as _Path
    ddir = _Path(data_dir) if data_dir else None

    # 2.1 — forward-analytics scorecard (risk-adjusted, evidenced-bars only).
    try:
        from spa_core.strategy_lab import forward_analytics as _fa
        card = _fa.build_scorecard(data_dir=ddir, write=True)
        print(
            f"  forward_an  : {card.get('n_tracks')} tracks "
            f"(beats {card.get('n_beats_floor')} · thin {card.get('n_thin_track')} · "
            f"unknown {card.get('n_unknown')} · dsr_active {card.get('n_dsr_active')})"
        )
    except Exception as _fa_exc:  # noqa: BLE001 — never crash the cycle
        log.warning("WS2.1 forward_analytics scorecard failed (non-critical): %s", _fa_exc)

    # 2.1b — day-30 readiness artifact (WS5): refresh the equity-proof-chain anchor over the
    # EVIDENCED bars, then write the AUTO/verifiable/hash-anchored day-30 readiness report. Both
    # are advisory / read-only over the live track (they never mutate it) and INDEPENDENTLY
    # fail-safe. Ordered AFTER 2.1 so the artifact embeds the fresh scorecard rollup, and BEFORE
    # 2.2 so the one-pager sources the fresh artifact. Honest at 7/30 today (verdict NOT_READY).
    try:
        from spa_core.audit import equity_proof_chain as _epc
        _epc.write_chain()   # refresh data/rates_desk/equity_track.jsonl (the artifact's anchor)
    except Exception as _epc_exc:  # noqa: BLE001 — never crash the cycle
        log.warning("WS5 equity_proof_chain refresh failed (non-critical): %s", _epc_exc)
    try:
        from spa_core.audit import day30_artifact as _d30
        _art = _d30.write_artifact(data_dir=ddir)
        print(
            f"  day30       : verdict={_art.get('verdict')} "
            f"readiness={_art.get('readiness_pct')}% "
            f"proof={(_art.get('proof_hash') or '')[:12]}…"
        )
    except Exception as _d30_exc:  # noqa: BLE001 — never crash the cycle
        log.warning("WS5 day30_artifact write failed (non-critical): %s", _d30_exc)

    # 2.1c — RISKWIRE day-30 REVIEW pipeline (WS1.3): the comprehensive, self-verifying review a
    # reviewer/funder reads the moment the evidenced track reaches 30 CONTINUOUS days. Ordered AFTER
    # 2.1b so it embeds the fresh readiness artifact (its proof_hash anchors the review). Composes
    # the honest reset story + realized risk-adjusted metrics (THIN→None below credible-N) + the
    # edge-at-scale verdict + the honest fundability framing + the continuity assertion (a gap → the
    # review REFUSES REVIEW_READY) + the refusal/proof surfaces. Writes data/riskwire/day30_review.json
    # + (canonical-only) docs/DAY30_REVIEW.md. Read-only over the track, INERT re: cutover, fail-safe.
    # Honest at 9/30 today (state TRACK_MATURING, "21 days to go").
    try:
        from spa_core.riskwire import day30_review as _d30r
        _rev = _d30r.write_review(data_dir=ddir)
        print(
            f"  day30_review: state={_rev.get('state')} "
            f"readiness={_rev.get('review_readiness_pct')}% "
            f"review_hash={(_rev.get('review_hash') or '')[:12]}…"
        )
    except Exception as _d30r_exc:  # noqa: BLE001 — never crash the cycle
        log.warning("WS1.3 day30_review write failed (non-critical): %s", _d30r_exc)

    # 2.2 — fundability one-pager (regenerates docs/FUNDABILITY.md from fresh data).
    try:
        import importlib.util as _ilu
        _root = _Path(__file__).resolve().parents[2]
        _spec = _ilu.spec_from_file_location(
            "spa_generate_fundability_onepager",
            str(_root / "scripts" / "generate_fundability_onepager.py"),
        )
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        _doc = _mod.generate(root=str(_root))
        _out = _root / "docs" / "FUNDABILITY.md"
        _mod.atomic_write(str(_out), _doc)
        print(f"  fundability : wrote {_out}")
    except Exception as _fp_exc:  # noqa: BLE001 — never crash the cycle
        log.warning("WS2.2 fundability one-pager failed (non-critical): %s", _fp_exc)

    # 2.3 — track_snapshot.json (the /track-record + /due-diligence offline fallback).
    # Auto-regenerated from the fresh golive_status + equity_curve so the site's build-time
    # fallback never drifts stale (it was hand-maintained and froze at 5 evidenced days while
    # the real track advanced — fixed by deriving it every live cycle). Advisory artifact.
    try:
        import importlib.util as _ilu2
        _root2 = _Path(__file__).resolve().parents[2]
        _spec2 = _ilu2.spec_from_file_location(
            "spa_generate_track_snapshot",
            str(_root2 / "scripts" / "generate_track_snapshot.py"),
        )
        _mod2 = _ilu2.module_from_spec(_spec2)
        _spec2.loader.exec_module(_mod2)
        _mod2.main()  # reads canonical data/, writes landing/src/data/track_snapshot.json (atomic)
        print("  track_snap  : regenerated landing/src/data/track_snapshot.json")
    except Exception as _ts_exc:  # noqa: BLE001 — never crash the cycle
        log.warning("track_snapshot regeneration failed (non-critical): %s", _ts_exc)


if __name__ == "__main__":
    raise SystemExit(main())
