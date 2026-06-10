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

MAX_TRADES = 500           # ring-buffer cap for trades.json
MAX_EQUITY_POINTS = 365    # ring-buffer cap for the daily equity curve
MAX_POLICY_BLOCKS = 100    # ring-buffer cap for risk_policy_blocks.json
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


# ─── Default orchestrator / allocator wiring (overridable for tests) ─────────


def _default_orchestrator(data_dir: Path):
    """Run the real read-only adapter orchestrator (writes its status file)."""
    from spa_core.orchestrator.adapter_orchestrator import run_orchestrator

    return run_orchestrator(write=True, data_dir=str(data_dir))


def _default_allocator(data_dir: Path):
    """Construct the real StrategyAllocator bound to this data dir's snapshot."""
    from spa_core.allocator.allocator import StrategyAllocator

    return StrategyAllocator(status_path=str(data_dir / ORCH_STATUS_FILENAME))


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
    write      : if False, computes everything but writes nothing (dry-run).
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    now_dt = now or datetime.now(timezone.utc)
    run_ts = now_dt.isoformat()
    today = now_dt.strftime("%Y-%m-%d")
    notes: list[str] = []

    orchestrator_fn = orchestrator_fn or _default_orchestrator

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
        )
        if write:
            _write_status(ddir, result, paper_start_date, capital_usd, run_ts)
        return result

    # ── Step 2: allocator → target allocation ─────────────────────────────
    alloc = (allocator or _default_allocator(ddir)).allocate()
    target_usd = {
        str(p): float(v) for p, v in (getattr(alloc, "target_usd", {}) or {}).items()
    }
    model_used = getattr(alloc, "model_used", None)
    strategy_loop_active = bool(getattr(alloc, "strategy_loop_active", False))

    # ── Step 2b (MP-005): deterministic RiskPolicy gate before any trade ──
    gate = _apply_risk_policy_gate(target_usd, capital_usd, adapters)
    policy_checked = gate["error"] is None
    policy_blocked = False
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
    elif policy_blocked:
        # Blocked rebalance: hold the previous positions; a first-ever cycle
        # that is blocked deploys nothing (the gate prevented the entry).
        effective_positions = dict(current_positions)
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
    result = CycleResult(
        run_ts=run_ts,
        date=today,
        status="blocked_by_policy" if policy_blocked else "ok",
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

    return result


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
    }
    _atomic_write_json(ddir / STATUS_FILENAME, doc)


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
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    result = run_cycle(data_dir=args.data_dir, write=not args.dry_run)
    _print_report(result)
    if args.dry_run:
        print("(dry-run: no files written)")
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
