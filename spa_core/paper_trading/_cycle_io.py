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
import os
import tempfile
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


# ─── Write-interlock (track-integrity guard) ─────────────────────────────────
#
# The PAPER_REAL_START_DATE constant above is honest *labelling*: it stops an
# ad-hoc run from inflating the real-track length, but it does NOT stop a stray
# `python3 -m spa_core.paper_trading.cycle_runner` in a dev shell from
# physically OVERWRITING the canonical live track files (this corrupted the
# track on 2026-06-25). This block adds a real, fail-CLOSED write-interlock.
#
# Rule (default-DENY): a cycle may write the canonical live data dir
# (<repo>/data) ONLY when the operator explicitly opts in via the `--live` CLI
# flag or the `SPA_ALLOW_LIVE_WRITE=1` environment variable. Without opt-in,
# writes are redirected to a sandbox dir — `SPA_DATA_DIR` if set, else a
# deterministic per-repo temp sandbox — so the canonical track is never mutated
# by accident. An explicitly-passed `data_dir` that is NOT the canonical dir is
# always honoured verbatim (tests / sandboxed callers control their own paths).

# Env names (single source of truth so callers/tests don't hardcode strings).
LIVE_WRITE_ENV = "SPA_ALLOW_LIVE_WRITE"
DATA_DIR_ENV = "SPA_DATA_DIR"


def _env_truthy(name: str) -> bool:
    """True iff env var ``name`` is set to an explicit affirmative value."""
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _default_sandbox_dir() -> Path:
    """Deterministic per-repo sandbox dir for default-deny (no-opt-in) runs.

    Honors ``SPA_DATA_DIR`` if set (the established sandbox convention used by
    the API server / feed runners); otherwise a stable temp dir keyed to this
    repo so it is predictable and never the canonical ``<repo>/data``.
    """
    override = os.environ.get(DATA_DIR_ENV, "").strip()
    if override:
        return Path(override)
    return Path(tempfile.gettempdir()) / "spa_cycle_sandbox" / _REPO_ROOT.name


def resolve_data_dir(
    data_dir: str | os.PathLike | None,
    *,
    allow_live_write: bool,
) -> tuple[Path, bool]:
    """Resolve the effective data dir under the write-interlock (fail-CLOSED).

    Returns ``(effective_dir, redirected)`` where ``redirected`` is True iff a
    canonical-track write was DENIED and rerouted to the sandbox.

    Semantics
    ---------
    * Explicit non-canonical ``data_dir`` → honoured verbatim (caller owns it).
    * Target would be the canonical ``<repo>/data``:
        - opt-in present (``allow_live_write`` flag OR ``SPA_ALLOW_LIVE_WRITE``
          env truthy) → canonical dir, live write permitted.
        - NO opt-in (DEFAULT) → DENY: redirect to ``_default_sandbox_dir()``
          and log loudly. The canonical track is never touched.
    """
    requested = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    is_canonical = requested.resolve() == _DEFAULT_DATA_DIR.resolve()
    if not is_canonical:
        return requested, False

    opted_in = bool(allow_live_write) or _env_truthy(LIVE_WRITE_ENV)
    if opted_in:
        log.info(
            "write-interlock: live write to canonical track ENABLED "
            "(--live / %s) → %s",
            LIVE_WRITE_ENV,
            _DEFAULT_DATA_DIR,
        )
        return _DEFAULT_DATA_DIR, False

    sandbox = _default_sandbox_dir()
    sandbox.mkdir(parents=True, exist_ok=True)
    log.warning(
        "write-interlock: DENIED canonical-track write (no --live / %s=1) — "
        "redirecting all writes to sandbox %s. The live track at %s is "
        "UNTOUCHED. Pass --live (or set %s=1) for a real production cycle.",
        LIVE_WRITE_ENV,
        sandbox,
        _DEFAULT_DATA_DIR,
        LIVE_WRITE_ENV,
    )
    return sandbox, True
