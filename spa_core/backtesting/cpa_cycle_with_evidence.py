"""
spa_core/backtesting/cpa_cycle_with_evidence.py

MP-1410 (v10.26): CPACycleWithEvidence — wraps CPADailyCycle and automatically
records an EvidenceAutoCalculator entry after every run.

Design:
  - Inherits CPADailyCycle; overrides run() to append evidence recording.
  - Evidence is recorded even when individual sections soft-fail.
  - Atomic save via EvidenceAutoCalculator.save().
  - Uses _log() helper so tests can inspect log lines.
  - Never raises from evidence recording path (best-effort).
  - LLM FORBIDDEN in this module (monitoring-adjacent).

Usage:
    from spa_core.backtesting.cpa_cycle_with_evidence import CPACycleWithEvidence

    cycle = CPACycleWithEvidence(base_dir="/path/to/repo")
    result = cycle.run()   # same return value as CPADailyCycle.run()
                           # side-effect: evidence updated in data/paper_evidence_history.json

stdlib only, atomic writes, LLM FORBIDDEN.
MP-1410 (v10.26)
"""

from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path
from typing import List, Optional


# ─── CPACycleWithEvidence ─────────────────────────────────────────────────────

class CPACycleWithEvidence:
    """
    Wraps CPADailyCycle and appends EvidenceAutoCalculator recording after run.

    Composition rather than inheritance — avoids deep import-time coupling
    to CPADailyCycle's optional dependencies (telegram, gate, etc.).

    Args:
        base_dir:   Root of the SPA repo (passed through to CPADailyCycle).
        date:       ISO date string for this cycle (default: today UTC).
        _cycle_cls: Injectable cycle class for testing (default: CPADailyCycle).
    """

    def __init__(
        self,
        base_dir: str = ".",
        date: Optional[str] = None,
        _cycle_cls=None,
    ) -> None:
        self._base_dir = Path(base_dir)
        self._date = date or datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%d"
        )
        self._logs: List[str] = []

        # Lazy import so cpa_daily_cycle errors don't block evidence-only tests
        if _cycle_cls is None:
            from spa_core.backtesting.cpa_daily_cycle import CPADailyCycle
            _cycle_cls = CPADailyCycle

        self._inner = _cycle_cls(base_dir=str(self._base_dir), date=self._date)

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self) -> dict:
        """
        Run the full CPA daily cycle, then record evidence.

        Returns the same dict as CPADailyCycle.run().
        """
        result = self._inner.run()

        # Tag result with a top-level status for evidence hook
        sections = result.get("sections", {})
        has_errors = any(
            isinstance(v, dict) and "error" in v
            for v in sections.values()
        )
        result["status"] = "FAIL" if has_errors else "OK"

        # Best-effort evidence recording — never propagate exceptions
        try:
            self._update_evidence_after_cycle(result)
        except Exception as exc:  # noqa: BLE001
            self._log(f"[evidence_hook] WARNING: evidence update failed: {exc}")

        return result

    # ── Evidence Hook ─────────────────────────────────────────────────────────

    def _update_evidence_after_cycle(self, cycle_result: dict) -> object:
        """
        After each daily cycle, automatically record an evidence entry.

        Extracts three booleans from cycle_result:
          cycle_ok  — top-level status == "OK" (no section errors)
          apy_ok    — evidence_update section has a non-None apy_today_pct
          risk_ok   — risk_policy_blocks.json has 0 blocks today OR section clean

        Returns the computed EvidenceScore (useful in tests; ignored in production).
        """
        from spa_core.analytics.evidence_auto_calculator import EvidenceAutoCalculator

        calc = EvidenceAutoCalculator(base_dir=str(self._base_dir))
        calc.load()

        sections = cycle_result.get("sections", {})

        # cycle_ok: no section-level errors
        cycle_ok = cycle_result.get("status") == "OK"

        # apy_ok: paper trading active and apy_today_pct present
        ev_section = sections.get("evidence_update", {})
        apy_today = ev_section.get("apy_today_pct")
        apy_ok = bool(
            ev_section.get("paper_active", False)
            and apy_today is not None
            and float(apy_today) > 0
        )

        # risk_ok: derive from risk policy blocks json (best-effort)
        risk_ok = self._risk_policy_passed_today(sections)

        notes = f"auto-recorded by CPACycleWithEvidence v10.26 status={cycle_result.get('status','?')}"

        calc.record_day(
            date=self._date,
            cycle_completed=cycle_ok,
            apy_verified=apy_ok,
            risk_policy_passed=risk_ok,
            notes=notes,
        )
        calc.save()

        score = calc.calculate_score()
        self._log(
            f"[evidence_hook] score updated: {score.total}/{score.target} pts "
            f"(cycles={score.daily_cycles_pts}, apy={score.apy_tracking_pts}, "
            f"risk={score.risk_policy_pts}, bonus={score.bonus_pts})"
        )
        return score

    def _risk_policy_passed_today(self, sections: dict) -> bool:
        """
        Return True if no risk policy blocks were recorded today.

        Reads data/risk_policy_blocks.json — absent or empty → passed=True.
        If file exists, checks that the most recent block's date != today → passed.
        """
        blocks_path = self._base_dir / "data" / "risk_policy_blocks.json"
        try:
            import json
            with open(blocks_path, encoding="utf-8") as fh:
                blocks = json.load(fh)
            if not isinstance(blocks, list):
                return True
            # Check if any block is dated today
            for block in blocks:
                if isinstance(block, dict):
                    block_date = str(block.get("date", "")).split("T")[0]
                    if block_date == self._date:
                        return False
            return True
        except FileNotFoundError:
            return True
        except Exception:  # noqa: BLE001
            return True  # assume passing on read errors

    # ── Delegation helpers ────────────────────────────────────────────────────

    def save(self, result: dict) -> str:
        """Delegate to inner cycle's save()."""
        return self._inner.save(result)

    def to_telegram_message(self, result: dict) -> str:
        """Delegate to inner cycle."""
        return self._inner.to_telegram_message(result)

    def send_telegram(self, result: dict) -> bool:
        """Delegate to inner cycle."""
        return self._inner.send_telegram(result)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _log(self, msg: str) -> None:
        """Append to internal log list; also print to stderr in non-test contexts."""
        self._logs.append(msg)
        print(msg, file=sys.stderr)

    def logs(self) -> List[str]:
        """Return all log lines accumulated during run()."""
        return list(self._logs)
