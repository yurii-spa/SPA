#!/usr/bin/env python3
"""Shared low-level primitives for the cycle_runner package (N12 decomposition).

PURE-MOVE EXTRACTION: this module holds the atomic-IO helpers and the constants
that ``cycle_runner.py`` and its extracted submodules (``equity``, ``risk_gate``,
``cycle_reporting``) all need. It exists only to break what would otherwise be a
circular import (cycle_runner imports the submodules; the submodules need the
shared helpers/constants that historically lived in cycle_runner). The bodies
below are byte-identical to their original definitions in cycle_runner.py — no
behaviour change.

stdlib only. Atomic writes via the centralized ``atomic_save`` (MP-1453).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.cycle_runner")

# ─── Configuration ───────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

# Paper trading start date (Day 0) — see CLAUDE.md / go-live criterion 1.
# Real track started 2026-06-10 (all data before this date is demo/invalid after teardown).
PAPER_START_DATE = "2026-06-10"
# Canonical real-track anchor (date object). The honest track NEVER starts before
# this date. `_summarize` computes real_days / first_real_date strictly off this
# anchor so an ad-hoc cycle run over a legacy (unflagged) curve can never inflate
# the real-track length by counting pre-teardown warmup bars. See
# golive_checker.PAPER_REAL_START (same date) — the two must agree.
PAPER_REAL_START_DATE = datetime.strptime(PAPER_START_DATE, "%Y-%m-%d").date()
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
# Rebalance when |Δallocation| exceeds 0.2% of capital (paper-mode turnover filter).
# $200 threshold on $100K capital — was $1,000 (1%) which was too high for paper trading.
DEFAULT_TRADE_THRESHOLD_PCT = 0.002


# ─── Atomic IO helpers (stdlib only) ─────────────────────────────────────────


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(obj, str(path))


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
