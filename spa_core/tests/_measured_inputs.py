"""Measured kill-switch inputs for cycle sandboxes (ADR-531).

Since ADR-531 a missing / stale / unreadable ``red_flags.json`` is UNMEASURED and the daily cycle
HOLDS (LAW 1) instead of reading it as «all clear». A sandbox that wants the ordinary path must
therefore carry the input the real ``com.spa.red_flag_monitor`` always writes: fresh, with live
category provenance and (here) no flags. One helper, so every fixture writes the same shape.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def write_measured_red_flags(data_dir, now: datetime | None = None, flags: list | None = None) -> Path:
    """Write a fresh, live, flag-free ``red_flags.json`` (generated at ``now`` — the cycle's clock)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    path = Path(data_dir) / "red_flags.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "generated_at": now.isoformat(), "fallback_used": False, "sources": ["defillama"],
        "provenance": {"by_category": {"tvl_drop": "live", "apy_spike": "live",
                                       "governance_proposal": "live", "token_unlock": "live"}},
        "red_flags": list(flags or []),
    }), encoding="utf-8")
    return path


def write_measured_kill_inputs(data_dir, now: datetime | None = None) -> None:
    """Everything the kill switch reads, measured: red flags + (if absent) a held book and an
    evidenced equity curve, so ``evaluate_triggers`` can say CLEAR rather than UNMEASURED.
    Existing scene files are never overwritten."""
    from datetime import timedelta
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    d = Path(data_dir)
    write_measured_red_flags(d, now)
    pos = d / "current_positions.json"
    if not pos.exists():
        pos.write_text(json.dumps({"positions": {"aave_v3": 50_000.0}, "cash_usd": 50_000.0}),
                       encoding="utf-8")
    curve = d / "equity_curve_daily.json"
    if not curve.exists():
        bars = [{"date": (now - timedelta(days=40 - i)).date().isoformat(),
                 "close_equity": 100_000.0 + i, "open_equity": 100_000.0 + i} for i in range(40)]
        curve.write_text(json.dumps({"source": "cycle_runner", "daily": bars}), encoding="utf-8")
