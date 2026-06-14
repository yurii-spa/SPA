#!/usr/bin/env python3
"""spa_core.audit.decision_audit — MP-310 Decision Audit Trail.

Lightweight correlation-id–linked audit chain logger for each paper-trading
allocation cycle.  Connects:

    new_cycle → log_snapshot → log_proposal → log_risk_check
              → log_trade | log_rejection

Key guarantees
--------------
* Stdlib only — no external dependencies.
* All writes to ``data/decision_audit.json`` are atomic (mkstemp + os.replace).
* JSONL append to ``data/audit_trail.jsonl`` is append-only (safe without atomicity).
* Every log_* method is fail-safe (catches all exceptions, never raises).
* Every log_* method returns *self* for fluent chaining.
* ``run_audit_export()`` is module-level, never raises.

On-disk
-------
``data/decision_audit.json`` — dict keyed by correlation_id; each value is a
list of event dicts in insertion order.

``data/audit_trail.jsonl`` — append-only JSONL; each line is one JSON object
with the full chain exported at that moment.

Public API
----------
DecisionAuditLogger:
    new_cycle(snapshot_id=None) -> str
    log_snapshot(cid, equity, positions, apy, paper_days) -> self
    log_proposal(cid, strategy, allocations, rationale) -> self
    log_risk_check(cid, passed, violations, warnings) -> self
    log_trade(cid, trade_id, protocol, amount_usd, action) -> self
    log_rejection(cid, reason) -> self
    export_cycle(cid) -> dict
    export_jsonl(output_path=None) -> None

run_audit_export(data_dir=None) -> None
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ── Paths / constants ─────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
_AUDIT_FILENAME = "decision_audit.json"
_JSONL_FILENAME = "audit_trail.jsonl"


# ── I/O helpers ───────────────────────────────────────────────────────────────


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, data: Any) -> None:
    """Write *data* as JSON to *path* atomically via mkstemp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.replace(tmp, str(path))


def _read_json_safe(path: Path, default: Any) -> Any:
    """Read JSON from *path*; return *default* on any error (corrupt / missing)."""
    try:
        with open(str(path), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


# ── Main class ────────────────────────────────────────────────────────────────


class DecisionAuditLogger:
    """Correlation-id–linked audit trail for paper-trading allocation cycles.

    Usage::

        a = DecisionAuditLogger(data_dir="/path/to/data")
        cid = a.new_cycle()
        a.log_snapshot(cid, equity=100_000, positions={"aave_v3": 40_000},
                       apy=5.2, paper_days=3)
        a.log_proposal(cid, strategy="S0", allocations={"aave_v3": 0.4},
                       rationale="highest_sharpe")
        a.log_risk_check(cid, passed=True, violations=[], warnings=[])
        a.log_trade(cid, trade_id="T001", protocol="aave_v3",
                    amount_usd=40_000, action="hold")
        chain = a.export_cycle(cid)
        a.export_jsonl()
    """

    def __init__(self, data_dir: str | Path | None = None) -> None:
        if data_dir is None:
            self._ddir = _DEFAULT_DATA_DIR
        else:
            self._ddir = Path(data_dir)
        self._audit_path = self._ddir / _AUDIT_FILENAME
        # In-memory registry: dict[correlation_id -> list[event_dict]]
        self._registry: dict[str, list[dict]] = {}
        self._load()

    # ── Internal I/O ──────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load persisted audit data from disk into memory (best-effort)."""
        try:
            raw = _read_json_safe(self._audit_path, {})
            if isinstance(raw, dict):
                self._registry = raw
            else:
                self._registry = {}
        except Exception:
            self._registry = {}

    def _save(self) -> None:
        """Persist current in-memory registry to disk (atomic, never raises)."""
        try:
            _atomic_write_json(self._audit_path, self._registry)
        except Exception as exc:
            log.warning("decision_audit: _save failed (%s)", exc)

    def _append(self, correlation_id: str, entry: dict) -> None:
        """Append *entry* to the registry for *correlation_id* and persist."""
        try:
            if correlation_id not in self._registry:
                self._registry[correlation_id] = []
            self._registry[correlation_id].append(entry)
            self._save()
        except Exception as exc:
            log.warning("decision_audit: _append failed (%s)", exc)

    def _paper_day_for(self, correlation_id: str) -> Any:
        """Return paper_day from the snapshot entry for this cycle, or None."""
        try:
            for ev in self._registry.get(correlation_id, []):
                if ev.get("event_type") == "snapshot":
                    v = ev.get("paper_day")
                    if v is not None:
                        return v
        except Exception:
            pass
        return None

    # ── Public: lifecycle ─────────────────────────────────────────────────

    def new_cycle(self, snapshot_id: str | None = None) -> str:
        """Start a new audit cycle. Returns a fresh UUID4 correlation_id string."""
        correlation_id = str(uuid.uuid4())
        entry: dict = {
            "correlation_id": correlation_id,
            "event_type": "cycle_start",
            "timestamp": _now_iso(),
            "paper_day": None,
            "snapshot_id": snapshot_id,
        }
        self._append(correlation_id, entry)
        return correlation_id

    # ── Public: log_* (all fail-safe, return self) ────────────────────────

    def log_snapshot(
        self,
        correlation_id: str,
        equity: float,
        positions: dict,
        apy: float,
        paper_days: int | float,
    ) -> "DecisionAuditLogger":
        """Record the portfolio snapshot at the start of the cycle."""
        try:
            entry: dict = {
                "correlation_id": correlation_id,
                "event_type": "snapshot",
                "timestamp": _now_iso(),
                "paper_day": paper_days,
                "equity_usd": float(equity),
                "positions": dict(positions),
                "apy_pct": float(apy),
            }
            self._append(correlation_id, entry)
        except Exception as exc:
            log.warning("decision_audit: log_snapshot failed (%s)", exc)
        return self

    def log_proposal(
        self,
        correlation_id: str,
        strategy: str,
        allocations: dict,
        rationale: str,
    ) -> "DecisionAuditLogger":
        """Record the allocation proposal produced by StrategyAllocator."""
        try:
            entry: dict = {
                "correlation_id": correlation_id,
                "event_type": "allocation_proposal",
                "timestamp": _now_iso(),
                "paper_day": self._paper_day_for(correlation_id),
                "strategy": str(strategy),
                "allocations": dict(allocations),
                "rationale": str(rationale),
            }
            self._append(correlation_id, entry)
        except Exception as exc:
            log.warning("decision_audit: log_proposal failed (%s)", exc)
        return self

    def log_risk_check(
        self,
        correlation_id: str,
        passed: bool,
        violations: list,
        warnings: list,
    ) -> "DecisionAuditLogger":
        """Record the RiskPolicy gate verdict."""
        try:
            entry: dict = {
                "correlation_id": correlation_id,
                "event_type": "risk_verdict",
                "timestamp": _now_iso(),
                "paper_day": self._paper_day_for(correlation_id),
                "passed": bool(passed),
                "violations": list(violations),
                "warnings": list(warnings),
            }
            self._append(correlation_id, entry)
        except Exception as exc:
            log.warning("decision_audit: log_risk_check failed (%s)", exc)
        return self

    def log_trade(
        self,
        correlation_id: str,
        trade_id: str,
        protocol: str,
        amount_usd: float,
        action: str,
    ) -> "DecisionAuditLogger":
        """Record an executed (virtual) paper trade."""
        try:
            entry: dict = {
                "correlation_id": correlation_id,
                "event_type": "trade_executed",
                "timestamp": _now_iso(),
                "paper_day": self._paper_day_for(correlation_id),
                "trade_id": str(trade_id),
                "protocol": str(protocol),
                "amount_usd": float(amount_usd),
                "action": str(action),
            }
            self._append(correlation_id, entry)
        except Exception as exc:
            log.warning("decision_audit: log_trade failed (%s)", exc)
        return self

    def log_rejection(
        self,
        correlation_id: str,
        reason: str,
    ) -> "DecisionAuditLogger":
        """Record a trade rejection (blocked by RiskPolicy or other guard)."""
        try:
            entry: dict = {
                "correlation_id": correlation_id,
                "event_type": "trade_blocked",
                "timestamp": _now_iso(),
                "paper_day": self._paper_day_for(correlation_id),
                "reason": str(reason),
            }
            self._append(correlation_id, entry)
        except Exception as exc:
            log.warning("decision_audit: log_rejection failed (%s)", exc)
        return self

    # ── Public: export ────────────────────────────────────────────────────

    def export_cycle(self, correlation_id: str) -> dict:
        """Return the full event chain for *correlation_id* as a dict.

        Structure::

            {
                "correlation_id": "...",
                "events": [...],       # in insertion order
                "event_count": N,
            }

        Returns an empty chain dict if *correlation_id* is unknown.
        Never raises.
        """
        try:
            events = list(self._registry.get(correlation_id, []))
            return {
                "correlation_id": correlation_id,
                "events": events,
                "event_count": len(events),
            }
        except Exception as exc:
            log.warning("decision_audit: export_cycle failed (%s)", exc)
            return {
                "correlation_id": correlation_id,
                "events": [],
                "event_count": 0,
                "error": str(exc),
            }

    def export_jsonl(self, output_path: str | Path | None = None) -> None:
        """Append all current cycles to a JSONL file (one JSON object per line).

        Default output: ``data/audit_trail.jsonl``.
        Uses append mode — safe for concurrent writers (append-only log pattern).
        Never raises.
        """
        try:
            if output_path is None:
                out = self._ddir / _JSONL_FILENAME
            else:
                out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            ts = _now_iso()
            with open(str(out), "a", encoding="utf-8") as fh:
                for cid, events in self._registry.items():
                    line = json.dumps(
                        {
                            "correlation_id": cid,
                            "exported_at": ts,
                            "events": list(events),
                        },
                        ensure_ascii=False,
                    )
                    fh.write(line + "\n")
        except Exception as exc:
            log.warning("decision_audit: export_jsonl failed (%s)", exc)


# ── Module-level entry point ──────────────────────────────────────────────────


def run_audit_export(data_dir: str | Path | None = None) -> None:
    """Export the latest cycle's chain to ``data/audit_trail.jsonl``.

    Designed for integration at the END of cycle_runner.run_cycle().
    Reads the in-memory + on-disk registry, picks the most recently created
    cycle, and appends its full event chain as one JSONL line.

    Never raises — all errors are caught and logged as WARNING.
    """
    try:
        logger = DecisionAuditLogger(data_dir=data_dir)
        if not logger._registry:
            log.debug("decision_audit: registry empty — nothing to export")
            return
        # Most recently started cycle is the last key inserted.
        latest_id = list(logger._registry.keys())[-1]
        if data_dir is None:
            out = _DEFAULT_DATA_DIR / _JSONL_FILENAME
        else:
            out = Path(data_dir) / _JSONL_FILENAME
        out.parent.mkdir(parents=True, exist_ok=True)
        chain = logger.export_cycle(latest_id)
        line = json.dumps(
            {
                "correlation_id": latest_id,
                "exported_at": _now_iso(),
                "events": chain.get("events", []),
            },
            ensure_ascii=False,
        )
        with open(str(out), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        log.debug(
            "decision_audit: exported cycle %s (%d events)",
            latest_id,
            len(chain.get("events", [])),
        )
    except Exception as exc:
        log.warning("run_audit_export failed (%s) — continuing", exc)


# ── CLI ───────────────────────────────────────────────────────────────────────


def _cli_main(argv: list[str] | None = None) -> int:
    """CLI: ``python3 -m spa_core.audit.decision_audit --export``"""
    parser = argparse.ArgumentParser(
        prog="decision_audit",
        description="Decision Audit Trail (MP-310) — export cycle chains to JSONL.",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="Export the latest cycle's audit chain to data/audit_trail.jsonl.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        metavar="DIR",
        help="Override data directory (default: repo_root/data/).",
    )
    args = parser.parse_args(argv)

    if args.export:
        run_audit_export(data_dir=args.data_dir)
        print("Audit trail exported.")
        return 0

    # No flag → print summary.
    logger = DecisionAuditLogger(data_dir=args.data_dir)
    n = len(logger._registry)
    print(f"decision_audit: {n} cycle(s) in registry.")
    for cid, events in logger._registry.items():
        types = [e.get("event_type", "?") for e in events]
        print(f"  {cid[:8]}…  [{', '.join(types)}]")
    return 0


if __name__ == "__main__":
    sys.exit(_cli_main())
