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
   (unexpected exception) is logged as WARNING and the gate is skipped
   (fail-open) — the cycle never crashes because of the gate.
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
import json
import logging
import math
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("spa.cycle_runner")

# ─── Configuration ───────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

# Paper trading start date (Day 0) — see CLAUDE.md / go-live criterion 1.
PAPER_START_DATE = "2026-05-20"
CAPITAL_USD = 100_000.0

TRADES_FILENAME = "trades.json"
EQUITY_FILENAME = "equity_curve_daily.json"
POSITIONS_FILENAME = "current_positions.json"
STATUS_FILENAME = "paper_trading_status.json"
ORCH_STATUS_FILENAME = "adapter_orchestrator_status.json"
RISK_BLOCKS_FILENAME = "risk_policy_blocks.json"
# MP-012: risk-score snapshot regenerated each cycle BEFORE allocation.
RISK_SCORES_FILENAME = "risk_scores.json"
# MP-108: kill-switch status file.
KILL_SWITCH_STATUS_FILENAME = "kill_switch_status.json"
# SPA-V434: dashboard cycle-metrics history.
DASHBOARD_HISTORY_FILENAME = "dashboard_metrics_history.json"

MAX_TRADES = 500           # ring-buffer cap for trades.json
MAX_EQUITY_POINTS = 365    # ring-buffer cap for the daily equity curve
MAX_POLICY_BLOCKS = 100    # ring-buffer cap for risk_policy_blocks.json
MAX_DASHBOARD_ENTRIES = 365  # ring-buffer cap for dashboard_metrics_history.json
# Rebalance only when |Δallocation| exceeds 1% of capital (turnover filter).
DEFAULT_TRADE_THRESHOLD_PCT = 0.01


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
    # MP-310: audit trail correlation id for this cycle.
    correlation_id: str = ""

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
            "correlation_id": self.correlation_id,
        }


# ─── Atomic IO helpers (stdlib only) ─────────────────────────────────────────


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Write JSON atomically: tmpfile in the same dir + os.replace (rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        finally:
            raise


def _read_json(path: Path, default: Any) -> Any:
    """Read JSON defensively. Missing/corrupt file → ``default`` (never raises)."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("%s unreadable (%s) — using default", path.name, exc)
        return default


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


def _accrue_daily_yield(
    positions: dict[str, float], apy_map: dict[str, float]
) -> float:
    """Sum one day of yield across positions: Σ pos_usd × apy% / 100 / 365."""
    total = 0.0
    for pool, usd in positions.items():
        apy = apy_map.get(pool)
        if apy is None or not isinstance(usd, (int, float)):
            continue
        total += float(usd) * float(apy) / 100.0 / 365.0
    return total


def _days_running(today: str, start: str = PAPER_START_DATE) -> int:
    """Calendar days elapsed since paper-trading start (inclusive, ≥ 1)."""
    try:
        d0 = datetime.strptime(start, "%Y-%m-%d").date()
        d1 = datetime.strptime(today, "%Y-%m-%d").date()
        return max(1, (d1 - d0).days + 1)
    except ValueError:
        return 1


# ─── Equity-curve maintenance ────────────────────────────────────────────────


def _rebuild_summary(daily: list[dict]) -> dict:
    """Recompute the roll-up summary over the daily bars (schema-compatible)."""
    if not daily:
        return {
            "num_days": 0,
            "num_snapshots": 0,
            "start_equity": 0.0,
            "end_equity": 0.0,
            "total_return_pct": 0.0,
            "best_day": None,
            "worst_day": None,
            "max_drawdown_pct": 0.0,
            "positive_days": 0,
            "negative_days": 0,
            "daily_volatility_pct": 0.0,
            "first_date": None,
            "last_date": None,
        }

    start_equity = float(daily[0].get("open_equity", daily[0].get("close_equity", 0.0)))
    end_equity = float(daily[-1].get("close_equity", 0.0))
    rets = [float(d.get("daily_return_pct", 0.0)) for d in daily]
    # Day 1 has a synthetic 0.0 return — exclude from best/worst/vol stats.
    real_rets = [
        (d.get("date"), float(d.get("daily_return_pct", 0.0))) for d in daily[1:]
    ]
    best = max(real_rets, key=lambda x: x[1], default=None)
    worst = min(real_rets, key=lambda x: x[1], default=None)

    peak = float("-inf")
    max_dd = 0.0
    for d in daily:
        close = float(d.get("close_equity", 0.0))
        peak = max(peak, close)
        if peak > 0:
            dd = (close / peak - 1.0) * 100.0
            max_dd = min(max_dd, dd)

    positive = sum(1 for _, r in real_rets if r > 0)
    negative = sum(1 for _, r in real_rets if r < 0)

    # Population stdev of the real daily returns (stdlib, no numpy).
    vol = 0.0
    vals = [r for _, r in real_rets]
    if len(vals) >= 1:
        mean = sum(vals) / len(vals)
        vol = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5

    return {
        "num_days": len(daily),
        "num_snapshots": len(daily),
        "start_equity": round(start_equity, 2),
        "end_equity": round(end_equity, 2),
        "total_return_pct": round((end_equity / start_equity - 1.0) * 100.0, 4)
        if start_equity
        else 0.0,
        "best_day": {"date": best[0], "daily_return_pct": round(best[1], 4)}
        if best
        else None,
        "worst_day": {"date": worst[0], "daily_return_pct": round(worst[1], 4)}
        if worst
        else None,
        "max_drawdown_pct": round(max_dd, 4),
        "positive_days": positive,
        "negative_days": negative,
        "daily_volatility_pct": round(vol, 4),
        "first_date": daily[0].get("date"),
        "last_date": daily[-1].get("date"),
    }


def _upsert_equity_point(
    equity_doc: dict,
    *,
    date: str,
    apy_today_pct: float,
    positions: dict[str, float],
    apy_map: dict[str, float],
    run_ts: str,
) -> tuple[dict, float, float, float]:
    """Append or refresh today's daily bar, idempotently per UTC day.

    Returns ``(equity_doc, close_equity, daily_yield_usd, daily_return_pct)``.

    The day's yield is always computed off the *previous* day's close, so a
    second run on the same date recomputes (rather than compounds) the bar.
    """
    daily: list[dict] = list(equity_doc.get("daily") or [])

    # Drop a same-date trailing bar so we recompute it from the prior close.
    if daily and daily[-1].get("date") == date:
        daily = daily[:-1]

    prev_close = float(daily[-1]["close_equity"]) if daily else CAPITAL_USD
    daily_yield = _accrue_daily_yield(positions, apy_map)
    close_equity = round(prev_close + daily_yield, 6)

    daily_return_pct = (
        round((close_equity / prev_close - 1.0) * 100.0, 6) if prev_close else 0.0
    )
    # Day 1 convention: first ever bar has a 0.0 daily return.
    if not daily:
        daily_return_pct = 0.0

    first_open = float(daily[0]["open_equity"]) if daily else prev_close
    cumulative_return_pct = (
        round((close_equity / first_open - 1.0) * 100.0, 6) if first_open else 0.0
    )

    peak = close_equity
    for d in daily:
        peak = max(peak, float(d.get("close_equity", 0.0)))
    drawdown_pct = round((close_equity / peak - 1.0) * 100.0, 6) if peak else 0.0

    bar = {
        "date": date,
        "open_equity": round(prev_close, 2),
        "close_equity": round(close_equity, 2),
        "high_equity": round(max(prev_close, close_equity), 2),
        "low_equity": round(min(prev_close, close_equity), 2),
        "snapshots": 1,
        "daily_return_pct": daily_return_pct,
        "cumulative_return_pct": cumulative_return_pct,
        "drawdown_pct": drawdown_pct,
        # SPA-V409: flat fields requested for the real cycle track record.
        "equity": round(close_equity, 2),
        "apy_today": round(apy_today_pct, 4),
        "daily_yield_usd": round(daily_yield, 4),
        "positions": {p: round(v, 2) for p, v in positions.items()},
    }
    daily.append(bar)
    daily = daily[-MAX_EQUITY_POINTS:]  # ring-buffer

    equity_doc = {
        "generated_at": run_ts,
        "source": "cycle_runner",
        "execution_mode": "read_only_simulation",
        "is_demo": False,
        "summary": _rebuild_summary(daily),
        "daily": daily,
    }
    return equity_doc, close_equity, daily_yield, daily_return_pct


# ─── MP-005: deterministic RiskPolicy gate ───────────────────────────────────


def _apply_risk_policy_gate(
    target_usd: dict[str, float],
    capital_usd: float,
    adapters: list[dict],
) -> dict:
    """Validate the allocator's target against ``RiskPolicy`` (MP-005).

    The target is replayed position-by-position through
    ``RiskPolicy.check_new_position()`` on a fresh ``PortfolioState`` so the
    cumulative limits (per-protocol concentration, total-T2 cap, cash buffer)
    see the *whole* target allocation, not just one trade.

    min-cash handling: a target that deploys past ``1 - min_cash_pct`` of
    capital is trimmed proportionally instead of blocked (per MP-005 spec).

    Returns a dict::

        approved    bool — False → the rebalance trade must NOT be recorded
        violations  list[str] — blocking violations ("<pool>: <reason>")
        warnings    list[str] — non-blocking policy warnings
        trimmed     bool — target was scaled down to the min-cash buffer
        target_usd  dict — the (possibly trimmed) allocation to use downstream
        error       str | None — the gate itself failed → fail-open, log only

    Never raises: any unexpected exception is captured into ``error`` so a
    broken gate degrades to a logged WARNING instead of crashing the cycle.
    """
    out: dict = {
        "approved": True,
        "violations": [],
        "warnings": [],
        "trimmed": False,
        "target_usd": dict(target_usd),
        "error": None,
    }
    try:
        from spa_core.risk.policy import PortfolioState, Position, RiskPolicy

        policy = RiskPolicy()
        cfg = policy.config

        meta: dict[str, dict] = {}
        for a in adapters:
            if isinstance(a, dict) and a.get("protocol"):
                meta[str(a["protocol"])] = a

        adjusted = {
            str(p): float(v)
            for p, v in target_usd.items()
            if isinstance(v, (int, float)) and float(v) > 0
        }

        # min_cash: trim to the deployable maximum, do not block (MP-005 spec).
        # floor() keeps the trimmed total strictly ≤ the cap despite rounding.
        max_deploy = capital_usd * (1.0 - cfg.min_cash_pct)
        total = sum(adjusted.values())
        if total > max_deploy and total > 0:
            scale = max_deploy / total
            adjusted = {
                p: math.floor(v * scale * 100) / 100.0 for p, v in adjusted.items()
            }
            out["trimmed"] = True

        state = PortfolioState(total_capital_usd=capital_usd, positions=[])
        violations: list[str] = []
        warnings: list[str] = []
        for pool, usd in sorted(adjusted.items(), key=lambda kv: (-kv[1], kv[0])):
            m = meta.get(pool, {})
            tier = str(m.get("tier") or "T2").upper()
            apy = float(m.get("apy_pct") or 0.0)
            tvl = float(m.get("tvl_usd") or 0.0)
            # Chain-level limits apply only when the adapter reports its chain.
            # Without it, a per-pool placeholder prevents the single-chain cap
            # from falsely lumping every pool onto "ethereum".
            chain = str(m.get("chain") or f"unknown:{pool}")
            res = policy.check_new_position(
                state,
                protocol_key=pool,
                tier=tier,
                amount_usd=usd,
                current_apy=apy,
                tvl_usd=tvl,
                chain=chain,
            )
            warnings.extend(res.warnings)
            if not res.approved:
                violations.extend(f"{pool}: {v}" for v in res.violations)
            # Add the position regardless of the verdict so cumulative limits
            # (T2 total, concentration) are evaluated over the full target.
            state.positions.append(
                Position(
                    protocol_key=pool,
                    tier=tier,
                    asset="USDC",
                    amount_usd=usd,
                    apy_at_open=apy,
                    current_apy=apy,
                    chain=chain,
                )
            )

        out["violations"] = violations
        out["warnings"] = warnings
        out["approved"] = not violations
        out["target_usd"] = adjusted
    except Exception as exc:  # gate must never crash the cycle (MP-005 spec)
        log.warning("RiskPolicy gate failed (%s) — fail-open, cycle continues", exc)
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def _record_policy_block(
    ddir: Path,
    *,
    run_ts: str,
    date: str,
    gate: dict,
    current_positions: dict[str, float],
    capital_usd: float,
) -> None:
    """Append one audit record to ``risk_policy_blocks.json`` (ring-buffer 100)."""
    blocks = _read_json(ddir / RISK_BLOCKS_FILENAME, [])
    if not isinstance(blocks, list):
        blocks = []
    blocks.append(
        {
            "ts": run_ts,
            "date": date,
            "source": "cycle_runner",
            "policy_version": _policy_version(),
            "violations": list(gate.get("violations") or []),
            "warnings": list(gate.get("warnings") or []),
            "blocked_target_usd": {
                p: round(float(v), 2)
                for p, v in (gate.get("target_usd") or {}).items()
            },
            "held_positions_usd": {
                p: round(float(v), 2) for p, v in current_positions.items()
            },
            "capital_usd": capital_usd,
        }
    )
    blocks = blocks[-MAX_POLICY_BLOCKS:]  # ring-buffer
    _atomic_write_json(ddir / RISK_BLOCKS_FILENAME, blocks)


def _policy_version() -> str:
    """Active RiskConfig version for audit records (best-effort)."""
    try:
        from spa_core.risk.policy import RiskConfig

        return RiskConfig().version
    except Exception:
        return "unknown"


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


def _default_orchestrator(data_dir: Path):
    """Run the real read-only adapter orchestrator (writes its status file)."""
    from spa_core.orchestrator.adapter_orchestrator import run_orchestrator

    return run_orchestrator(write=True, data_dir=str(data_dir))


def _default_allocator(data_dir: Path):
    """Construct the real StrategyAllocator bound to this data dir's snapshot."""
    from spa_core.allocator.allocator import StrategyAllocator

    return StrategyAllocator(status_path=str(data_dir / ORCH_STATUS_FILENAME))


def _default_risk_scorer(data_dir: Path) -> None:
    """MP-012: regenerate ``data/risk_scores.json`` via the scoring engine.

    Invocation only — ALL scoring logic stays in
    ``spa_core/risk/scoring_engine.py`` (the cycle runner never computes a
    score itself; the allocator then reads the refreshed JSON snapshot).
    The engine writes atomically (tmpfile + os.replace) and is itself
    offline-tolerant (network failure → bootstrap fallback, never raises for
    that reason)."""
    from spa_core.risk.scoring_engine import RiskScoringEngine

    RiskScoringEngine().export(output_file=Path(data_dir) / RISK_SCORES_FILENAME)


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


def _default_track_persister(data_dir: Path) -> None:
    """MP-109: mirror the track into SQLite + run the daily off-site backup.

    Invocation only — ALL persistence logic lives in
    ``spa_core/persistence/track_store.py`` (idempotent SQLite mirror of
    ``trades.json`` / ``equity_curve_daily.json``; the JSON files stay the
    source of truth and are NEVER modified) and
    ``spa_core/persistence/backup.py`` (dated folder on iCloud Drive /
    ``$SPA_BACKUP_DIR``, sha256 manifest, 14-folder rotation). Both modules
    are themselves fail-safe, but the wrapper below catches everything anyway."""
    from spa_core.persistence.backup import run_backup
    from spa_core.persistence.track_store import TrackStore

    ddir = Path(data_dir)
    TrackStore(db_path=ddir / "track.db").sync_from_json(ddir)
    run_backup(ddir)


def _persist_track(
    ddir: Path,
    track_persister_fn: Callable[[Path], Any] | None,
    notes: list[str],
) -> bool:
    """MP-109 fail-safe wrapper: any exception → WARNING + note
    ``track_persist_failed``, the cycle NEVER fails because of
    persistence/backup. Never raises."""
    try:
        (track_persister_fn or _default_track_persister)(ddir)
        return True
    except Exception as exc:  # noqa: BLE001 — persistence must never crash the cycle
        log.warning(
            "track persistence/backup failed (%s) — cycle continues; the JSON "
            "track record is unaffected",
            exc,
        )
        notes.append(
            f"track_persist_failed: {type(exc).__name__}: {exc} — "
            "cycle continues; JSON track record unaffected."
        )
        return False


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
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
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

    # ── Step 0 (MP-006): go-live anti-demo gate — advisory, never blocks ──
    _run_golive_gate(ddir, now_dt, write)

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

    # Load prior persisted state up front (needed for both paths).
    current_positions: dict[str, float] = {
        k: float(v)
        for k, v in (_read_json(ddir / POSITIONS_FILENAME, {}).get("positions", {}) or {}).items()
    }
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
        )
        if write:
            _write_status(ddir, result, paper_start_date, capital_usd, run_ts)
            # MP-102: daily report after all steps (fail-safe, advisory).
            _run_daily_report(ddir, today)
            # SPA-V434: dashboard metrics snapshot (fail-safe, advisory).
            _save_cycle_snapshot_safe(ddir, result, adapters, run_ts)
        return result

    # ── Step 1b (MP-108): kill-switch check — override allocation if active ──
    # Deterministic, fail-safe: any exception → WARNING + note, cycle continues.
    # Kill-switch CANNOT be overridden by any agent (approved=False is final).
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
    except Exception as exc:  # kill-switch check must never crash the cycle
        log.warning("kill_switch check failed (%s) — fail-open, cycle continues", exc)
        notes.append(f"kill_switch_check_error: {type(exc).__name__}: {exc}")

    # ── Step 2: allocator → target allocation ─────────────────────────────
    alloc = (allocator or _default_allocator(ddir)).allocate()
    target_usd = {
        str(p): float(v) for p, v in (getattr(alloc, "target_usd", {}) or {}).items()
    }
    model_used = getattr(alloc, "model_used", None)
    strategy_loop_active = bool(getattr(alloc, "strategy_loop_active", False))

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

    # ── Step 2b (MP-005): deterministic RiskPolicy gate before any trade ──
    gate = _apply_risk_policy_gate(target_usd, capital_usd, adapters)
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
        notes.append(
            f"risk_policy_gate_error: {gate['error']} — gate skipped "
            "(fail-open, WARNING logged)."
        )
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
    if _ks_triggered and _ks_allocation:
        # Kill-switch overrides both the allocator and the risk policy gate.
        # All capital moves to cash; all protocol allocations set to 0.
        target_usd = {
            k: float(v) * capital_usd if k == "cash" else 0.0
            for k, v in _ks_allocation.items()
        }
        # Remove "cash" as a protocol entry — cash is the residual.
        target_usd = {k: v for k, v in target_usd.items() if k != "cash"}
        notes.append(
            "kill_switch_override: all protocol allocations set to 0 (all-cash)."
        )

    # ── Step 3: virtual rebalance trade if allocation moved > threshold ───
    trades: list[dict] = _read_json(ddir / TRADES_FILENAME, [])
    if not isinstance(trades, list):
        trades = []
    diff_usd = _allocation_diff_usd(current_positions, target_usd)
    threshold_usd = trade_threshold_pct * capital_usd
    traded = (not policy_blocked) and diff_usd > threshold_usd
    trade_id: str | None = None

    if traded:
        trade_id = _next_trade_id(trades)
        trades.append(
            {
                "trade_id": trade_id,
                "ts": run_ts,
                "type": "rebalance",
                "from_allocation": {p: round(v, 2) for p, v in current_positions.items()},
                "to_allocation": {p: round(v, 2) for p, v in target_usd.items()},
                "diff_usd": round(diff_usd, 2),
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
    equity_doc, close_equity, daily_yield, daily_return_pct = _upsert_equity_point(
        equity_doc,
        date=today,
        apy_today_pct=weighted_apy,
        positions=effective_positions,
        apy_map=apy_map,
        run_ts=run_ts,
    )

    days = _days_running(today, paper_start_date)
    # MP-108: status reflects kill-switch if active
    _cycle_status = "kill_switch" if _ks_triggered else ("blocked_by_policy" if policy_blocked else "ok")
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
        correlation_id=_correlation_id,
    )

    # ── Step 6: persist everything atomically ─────────────────────────────
    if write:
        _atomic_write_json(ddir / TRADES_FILENAME, trades)
        _atomic_write_json(ddir / EQUITY_FILENAME, equity_doc)
        _atomic_write_json(
            ddir / POSITIONS_FILENAME,
            {
                "generated_at": run_ts,
                "source": "cycle_runner",
                "execution_mode": "read_only_simulation",
                "is_demo": False,
                "capital_usd": capital_usd,
                "deployed_usd": round(deployed, 2),
                "cash_usd": round(capital_usd - deployed, 2),
                "model_used": model_used,
                "positions": {p: round(v, 2) for p, v in effective_positions.items()},
            },
        )
        _write_status(ddir, result, paper_start_date, capital_usd, run_ts)

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

        # ── MP-386: Multi-Strategy Tournament S2/S3 Integration ──────────────
        # Запускает MultiStrategyRunner с S0/S1/S2/S3 стратегиями.
        # S2 (Pendle PT + Morpho Heavy) и S3 (Aave Arbitrum L2 + Morpho)
        # преобразуются в StrategyConfig из модульных констант.
        # Advisory — не трогает trades.json, equity_curve, risk/policy.
        # Fail-safe: любое исключение → WARNING, цикл продолжается.
        try:
            from spa_core.paper_trading.strategy_registry import (
                S0_CONSERVATIVE_T1 as _ms_s0,
                S1_BALANCED as _ms_s1,
                StrategyConfig as _MSStrategyConfig,
            )
            from spa_core.paper_trading.multi_strategy_runner import (
                MultiStrategyRunner as _MultiStrategyRunner,
            )
            from spa_core.strategies.s2_pendle_morpho import (
                STRATEGY_ID as _s2_id,
                STRATEGY_NAME as _s2_name,
                TIER as _s2_tier,
                ALLOCATION as _s2_alloc,
                TARGET_APY_MIN as _s2_apy_min,
                TARGET_APY_MAX as _s2_apy_max,
            )
            from spa_core.strategies.s3_aave_arb_morpho import (
                STRATEGY_ID as _s3_id,
                STRATEGY_NAME as _s3_name,
                TIER as _s3_tier,
                ALLOCATION as _s3_alloc,
                TARGET_APY_MIN as _s3_apy_min,
                TARGET_APY_MAX as _s3_apy_max,
            )
            # S2: исключаем pendle_pt (external — в _SKIP_PROTOCOLS MultiStrategyRunner)
            _ms_s2 = _MSStrategyConfig(
                id=_s2_id,
                name=_s2_name,
                description="S2 Pendle PT + Morpho Heavy (pendle_pt excl.)",
                allocations={k: v for k, v in _s2_alloc.items() if k != "pendle_pt"},
                tier=_s2_tier,
                target_apy_min=_s2_apy_min,
                target_apy_max=_s2_apy_max,
            )
            # S3: все T1 — aave_arbitrum + morpho_steakhouse + aave_mainnet
            _ms_s3 = _MSStrategyConfig(
                id=_s3_id,
                name=_s3_name,
                description="S3 Aave Arbitrum L2 + Morpho (all T1)",
                allocations=dict(_s3_alloc),
                tier=_s3_tier,
                target_apy_min=_s3_apy_min,
                target_apy_max=_s3_apy_max,
            )
            _ms_strategies = [_ms_s0, _ms_s1, _ms_s2, _ms_s3]
            _ms_runner = _MultiStrategyRunner(
                strategies=_ms_strategies, capital=100_000
            )
            _ms_runner.run_day(apy_map=apy_map)
            _ms_rankings = _ms_runner.get_rankings()
            _ms_runner.export_results(ddir / "tournament_ranking.json")
            _ms_top = _ms_rankings[0] if _ms_rankings else None
            if _ms_top:
                log.info(
                    "MP-386 Tournament leader: %s APY=%.4f composite=%.3f",
                    _ms_top.get("strategy_id", "?"),
                    _ms_top.get("net_apy", 0.0),
                    _ms_top.get("composite_score", 0.0),
                )
        except Exception as _ms_exc:  # noqa: BLE001 — never crash the cycle
            log.warning("MultiStrategyRunner S2/S3 skipped: %s", _ms_exc)

        from spa_core.paper_trading.gap_monitor import check_gaps as _check_gaps
        try:
            _check_gaps()
        except Exception:
            pass  # fail-open

        # ── MP-111: milestone tracker (fail-safe, advisory) ──────────────
        # Runs AFTER gap_monitor so its gap_detected flag feeds the streak
        # check. Never blocks the cycle — any exception → WARNING only.
        try:
            from spa_core.milestone.milestone_tracker import (
                check_milestone,
                generate_milestone_report,
            )

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
            _run_reporting(data_dir=str(ddir), dry_run=False)
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

    return result


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
            from spa_core.agents.protocol_research_agent import run_research_cycle as _research_cycle
            _research_cycle(data_dir=ddir)
            results["protocol_research"] = "ok"
        except Exception as exc:  # noqa: BLE001
            log.warning("protocol_research_cycle failed (%s) — cycle continues", exc)
            results["protocol_research"] = f"error: {type(exc).__name__}: {exc}"

    return results


# ─── MP-016: Telegram alerts (fail-safe, advisory — never crash the cycle) ───


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
            sent["daily_summary"] = alert_manager.send_daily_summary(report)
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
            sent["red_flags"] = alert_manager.send_red_flag(flags)
    except Exception as exc:  # noqa: BLE001
        log.warning("red-flag alert failed (%s) — cycle continues", exc)

    try:
        gm = _read_json(ddir / "gap_monitor.json", {})
        if isinstance(gm, dict) and gm.get("gap_detected"):
            sent["gap"] = alert_manager.send_gap_alert(
                float(gm.get("hours_since_last_entry", 0.0) or 0.0)
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("gap alert failed (%s) — cycle continues", exc)

    return sent


def _write_status(
    ddir: Path,
    result: CycleResult,
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
        "last_trade_id": result.trade_id,
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
    result: CycleResult,
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
        "--no-monitors",
        action="store_true",
        help="skip the MP-107 external monitors (red flags / governance / incidents)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    result = run_cycle(data_dir=args.data_dir, write=not args.dry_run)
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
        monitors = _run_daily_monitors(args.data_dir)
        for name, status in monitors.items():
            print(f"  monitor {name:<12}: {status}")

    # MP-016: Telegram alerts after the cycle & monitors (fail-safe;
    # network-bound, hence here in the CLI and not inside run_cycle()).
    if not args.dry_run:
        alerts = _run_cycle_alerts(args.data_dir, date=result.date)
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
            pdf_path = generate_pdf_report(data_dir=args.data_dir)
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
            _suggestion = run_allocation_tuner(data_dir=_DEFAULT_DATA_DIR)
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

    if args.dry_run:
        print("(dry-run: no files written)")
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
