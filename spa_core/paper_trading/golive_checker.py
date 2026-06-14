#!/usr/bin/env python3
"""SPA go-live readiness checker — anti-demo gate (MP-006).

Validates that the paper-trading track record is REAL (not demo-seeded) and
recent enough to justify a go-live decision. All six criteria must pass:

1. ``data/equity_curve_daily.json`` exists, is marked ``is_demo: false`` and
   contains at least one daily bar.
2. ``data/trades.json`` contains at least one trade with ``is_demo: false``.
3. ``data/paper_trading_status.json`` exists with ``is_demo: false``.
4. NO ``*.json`` file anywhere under ``data/`` contains ``"is_demo": true``.
5. The equity curve has a bar within the last 48 hours (the cycle loop is
   alive, not stalled).
6. ``spa_core/paper_trading/cycle_runner.py`` exists (the real loop is
   deployed, not just its outputs).

The result is persisted to ``data/golive_status.json`` (atomic write) so the
dashboard and CLI read one canonical verdict.

Scope / safety
==============
* STRICTLY READ-ONLY over the track record; the only write is its own status
  file. Touches no capital, imports no execution/feed-health/risk-agent code.
* Stdlib only. Atomic writes (tmpfile + os.replace).
* Advisory: callers (``cycle_runner.run_cycle``) must NOT abort the cycle on
  ``ready=False`` — the cycle has to keep running to accumulate the very
  track record these criteria wait for.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

STATUS_OUT_FILENAME = "golive_status.json"
EQUITY_FILENAME = "equity_curve_daily.json"
TRADES_FILENAME = "trades.json"
PT_STATUS_FILENAME = "paper_trading_status.json"
CYCLE_RUNNER_REL = Path("spa_core") / "paper_trading" / "cycle_runner.py"

FRESHNESS_WINDOW_HOURS = 48

# Text fallback for criterion 4 when a file is not valid JSON.
_DEMO_TRUE_RE = re.compile(r'"is_demo"\s*:\s*true')


# ─── Result object ───────────────────────────────────────────────────────────


@dataclass
class GoLiveResult:
    """Verdict of one anti-demo go-live check."""

    ready: bool
    checks: dict[str, bool] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "ready": self.ready,
            "checks": dict(self.checks),
            "blockers": list(self.blockers),
            "timestamp": self.timestamp,
            "source": "golive_checker",
        }

    def summary(self) -> str:
        """Human-readable report for the CLI and the dashboard."""
        lines = [
            "─" * 56,
            f"GO-LIVE READINESS (anti-demo gate)   [{self.timestamp}]",
            "─" * 56,
        ]
        for name, ok in self.checks.items():
            lines.append(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        if self.blockers:
            lines.append("  blockers:")
            lines.extend(f"    • {b}" for b in self.blockers)
        lines.append(
            f"  verdict: {'READY' if self.ready else 'NOT READY'}"
            f" ({sum(self.checks.values())}/{len(self.checks)} checks pass)"
        )
        lines.append("─" * 56)
        return "\n".join(lines)


# ─── IO helpers (stdlib only, mirror cycle_runner conventions) ───────────────


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


def _read_json(path: Path) -> Any:
    """Read JSON defensively: missing/corrupt file → None (never raises)."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _contains_demo_true(obj: Any) -> bool:
    """Recursively detect ``"is_demo": true`` anywhere in a parsed JSON doc."""
    if isinstance(obj, dict):
        if obj.get("is_demo") is True:
            return True
        return any(_contains_demo_true(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_contains_demo_true(v) for v in obj)
    return False


# ─── Checker ─────────────────────────────────────────────────────────────────


class GoLiveChecker:
    """Anti-demo go-live gate over the ``data/`` track record (MP-006)."""

    def __init__(
        self,
        data_dir: str | os.PathLike | None = None,
        repo_root: str | os.PathLike | None = None,
        now: datetime | None = None,
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
        self.repo_root = Path(repo_root) if repo_root is not None else _REPO_ROOT
        self.now = now or datetime.now(timezone.utc)
        if self.now.tzinfo is None:
            self.now = self.now.replace(tzinfo=timezone.utc)

    # ── individual criteria ───────────────────────────────────────────────

    def _check_equity_curve(self, blockers: list[str]) -> bool:
        doc = _read_json(self.data_dir / EQUITY_FILENAME)
        if doc is None:
            blockers.append(f"{EQUITY_FILENAME}: missing or unreadable")
            return False
        if not isinstance(doc, dict) or doc.get("is_demo") is not False:
            blockers.append(f"{EQUITY_FILENAME}: not marked is_demo:false")
            return False
        daily = doc.get("daily")
        if not isinstance(daily, list) or not daily:
            blockers.append(f"{EQUITY_FILENAME}: no daily equity records")
            return False
        return True

    def _check_trades(self, blockers: list[str]) -> bool:
        trades = _read_json(self.data_dir / TRADES_FILENAME)
        if not isinstance(trades, list):
            blockers.append(f"{TRADES_FILENAME}: missing or unreadable")
            return False
        real = [
            t for t in trades if isinstance(t, dict) and t.get("is_demo") is False
        ]
        if not real:
            blockers.append(
                f"{TRADES_FILENAME}: no real (is_demo:false) trades recorded yet"
            )
            return False
        return True

    def _check_status(self, blockers: list[str]) -> bool:
        doc = _read_json(self.data_dir / PT_STATUS_FILENAME)
        if not isinstance(doc, dict):
            blockers.append(f"{PT_STATUS_FILENAME}: missing or unreadable")
            return False
        if doc.get("is_demo") is not False:
            blockers.append(f"{PT_STATUS_FILENAME}: not marked is_demo:false")
            return False
        return True

    def _check_no_demo_data(self, blockers: list[str]) -> bool:
        """Criterion 4: NO json file under data/ may contain ``is_demo: true``."""
        offenders: list[str] = []
        if self.data_dir.is_dir():
            for path in sorted(self.data_dir.rglob("*.json")):
                # Skip our own output and editor/atomic-write temp droppings.
                if path.name == STATUS_OUT_FILENAME or path.name.startswith("."):
                    continue
                doc = _read_json(path)
                if doc is not None:
                    demo = _contains_demo_true(doc)
                else:  # unparseable → conservative text scan
                    try:
                        demo = bool(
                            _DEMO_TRUE_RE.search(path.read_text(encoding="utf-8"))
                        )
                    except OSError:
                        demo = False
                if demo:
                    offenders.append(path.name)
        if offenders:
            blockers.append(
                "demo data detected (is_demo:true) in: " + ", ".join(offenders)
            )
            return False
        return True

    def _check_freshness(self, blockers: list[str]) -> bool:
        doc = _read_json(self.data_dir / EQUITY_FILENAME)
        daily = doc.get("daily") if isinstance(doc, dict) else None
        if not isinstance(daily, list) or not daily:
            blockers.append(
                f"{EQUITY_FILENAME}: no records to assess "
                f"{FRESHNESS_WINDOW_HOURS}h freshness"
            )
            return False
        latest: datetime | None = None
        for bar in daily:
            if not isinstance(bar, dict):
                continue
            try:
                dt = datetime.strptime(str(bar.get("date")), "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                continue
            if latest is None or dt > latest:
                latest = dt
        if latest is None:
            blockers.append(f"{EQUITY_FILENAME}: no parseable record dates")
            return False
        age = self.now - latest
        if age >= timedelta(hours=FRESHNESS_WINDOW_HOURS):
            blockers.append(
                f"{EQUITY_FILENAME}: last record {latest.date()} is "
                f"{age.total_seconds() / 3600.0:.0f}h old "
                f"(> {FRESHNESS_WINDOW_HOURS}h — cycle loop may be stalled)"
            )
            return False
        return True

    def _check_cycle_runner(self, blockers: list[str]) -> bool:
        path = self.repo_root / CYCLE_RUNNER_REL
        if not path.is_file():
            blockers.append(f"{CYCLE_RUNNER_REL}: missing — real cycle loop not deployed")
            return False
        return True

    # ── public API ────────────────────────────────────────────────────────

    def check(self, write: bool = True) -> GoLiveResult:
        """Run all six criteria; persist ``data/golive_status.json`` unless
        ``write=False``. Never raises on bad/missing data — that is a blocker,
        not an exception."""
        blockers: list[str] = []
        checks = {
            "equity_curve_real": self._check_equity_curve(blockers),
            "trades_real": self._check_trades(blockers),
            "status_real": self._check_status(blockers),
            "no_demo_data": self._check_no_demo_data(blockers),
            "data_fresh_48h": self._check_freshness(blockers),
            "cycle_runner_exists": self._check_cycle_runner(blockers),
        }
        result = GoLiveResult(
            ready=all(checks.values()),
            checks=checks,
            blockers=blockers,
            timestamp=self.now.isoformat(),
        )
        if write:
            _atomic_write_json(self.data_dir / STATUS_OUT_FILENAME, result.to_dict())
        return result


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="golive_checker",
        description="Anti-demo go-live readiness check (MP-006).",
    )
    parser.add_argument("--data-dir", default=None, help="override data directory")
    parser.add_argument(
        "--dry-run", action="store_true", help="do not write golive_status.json"
    )
    args = parser.parse_args(argv)

    result = GoLiveChecker(data_dir=args.data_dir).check(write=not args.dry_run)
    print(result.summary())
    return 0 if result.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
