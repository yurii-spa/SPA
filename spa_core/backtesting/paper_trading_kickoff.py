"""
spa_core/backtesting/paper_trading_kickoff.py

MP-1355 (v9.71) — Validates prerequisites and kicks off paper trading period.

Prerequisites checked:
  1. Gate: Backtest PASS         (pre_paper_backtest_gate.json status=PASS)
  2. Gate: Pre-Paper PASS        (paper_ready_gate.json — all blockers resolved OR waived)
  3. CPA Integration doc         (docs/CPA_INTEGRATION_STATUS.md exists)
  4. Owner acceptance signed     (data/backtest/owner_paper_acceptance.json accepted=true)
     or waive_acceptance=True
  5. Kill switch not triggered   (data/kill_switch_status.json triggered=false)

On kickoff:
  - Creates data/paper/paper_state.json  with start_date, day=0, etc.
  - Creates data/paper/kickoff_receipt.json
  - Returns KickoffResult

Rules:
  - stdlib only, no external dependencies
  - atomic writes: mkstemp + os.replace
  - all file reads defensive (missing / malformed → FAIL / warning, no raise)
  - LLM_FORBIDDEN in this module (pure deterministic)
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from spa_core.utils.atomic import atomic_save


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class PrerequisiteCheck:
    name: str
    passed: bool
    required: bool      # if True and not passed → blocking_issue
    notes: str = ""


@dataclass
class KickoffResult:
    success: bool
    start_date: str
    day_zero: bool
    prerequisites: List[PrerequisiteCheck]
    blocking_issues: List[str]
    warnings: List[str]
    receipt_path: Optional[str] = None


# ── Main class ────────────────────────────────────────────────────────────────

class PaperTradingKickoff:
    """
    Validates all prerequisites and kicks off the paper trading period.

    Usage::

        kickoff = PaperTradingKickoff(base_dir="/path/to/repo")

        # Inspect prerequisites
        checks = kickoff.check_prerequisites()
        for c in checks:
            print(c.name, "PASS" if c.passed else "FAIL")

        # Dry-run (no file writes)
        result = kickoff.kickoff(dry_run=True)

        # Real kickoff
        result = kickoff.kickoff(dry_run=False)
        if result.success:
            print("Paper trading started:", result.start_date)

    Args:
        base_dir:          Path to the repository root (default: current directory).
        waive_acceptance:  If True, owner acceptance check is non-required (allows
                           kickoff without a signed acceptance file, e.g. for initial
                           start when acceptance workflow hasn't been completed).
    """

    # Sub-paths (relative to base_dir)
    _PRE_PAPER_GATE  = "data/backtest/pre_paper_backtest_gate.json"
    _PAPER_READY     = "data/backtest/paper_ready_gate.json"
    _OWNER_ACCEPTANCE = "data/backtest/owner_paper_acceptance.json"
    _CPA_DOC         = "docs/CPA_INTEGRATION_STATUS.md"
    _KILL_SWITCH     = "data/kill_switch_status.json"
    _PAPER_STATE     = "data/paper/paper_state.json"
    _RECEIPT         = "data/paper/kickoff_receipt.json"

    def __init__(self, base_dir: str = ".", waive_acceptance: bool = False) -> None:
        self.base_dir = Path(base_dir)
        self.waive_acceptance = waive_acceptance

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _read_json(self, rel_path: str) -> Optional[dict]:
        """Read a JSON file relative to base_dir. Returns None on any error."""
        p = self.base_dir / rel_path
        try:
            with open(p, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError, ValueError):
            return None

    def _file_exists(self, rel_path: str) -> bool:
        return (self.base_dir / rel_path).exists()

    def _atomic_write(self, rel_path: str, data: dict) -> str:
        """Write data as JSON atomically using atomic_save. Returns abs path."""
        p = self.base_dir / rel_path
        atomic_save(data, str(p))
        return str(p)

    # ── Prerequisite checks ───────────────────────────────────────────────────

    def _check_backtest_gate(self) -> PrerequisiteCheck:
        """P1: pre_paper_backtest_gate.json status == PASS"""
        data = self._read_json(self._PRE_PAPER_GATE)
        if data is None:
            return PrerequisiteCheck(
                name="backtest_gate",
                passed=False,
                required=True,
                notes="pre_paper_backtest_gate.json not found or malformed",
            )
        passed = data.get("status") == "PASS"
        return PrerequisiteCheck(
            name="backtest_gate",
            passed=passed,
            required=True,
            notes="status=PASS" if passed else f"status={data.get('status', '?')}",
        )

    def _check_pre_paper_gate(self) -> PrerequisiteCheck:
        """P2: paper_ready_gate.json — paper_trading_allowed or no blocking blockers"""
        data = self._read_json(self._PAPER_READY)
        if data is None:
            return PrerequisiteCheck(
                name="pre_paper_gate",
                passed=False,
                required=True,
                notes="paper_ready_gate.json not found or malformed",
            )
        # Either paper_trading_allowed=True OR status=READY
        allowed = bool(data.get("paper_trading_allowed", False))
        status = data.get("status", "")
        passed = allowed or (status == "READY")
        blockers = data.get("blockers", [])
        notes_parts = []
        if passed:
            notes_parts.append("READY")
        else:
            notes_parts.append(f"status={status}")
            if blockers:
                notes_parts.append(f"blockers: {', '.join(str(b) for b in blockers[:2])}")
        return PrerequisiteCheck(
            name="pre_paper_gate",
            passed=passed,
            required=True,
            notes="; ".join(notes_parts),
        )

    def _check_cpa_doc(self) -> PrerequisiteCheck:
        """P3: CPA Integration status document exists"""
        exists = self._file_exists(self._CPA_DOC)
        return PrerequisiteCheck(
            name="cpa_integration_doc",
            passed=exists,
            required=True,
            notes=f"{self._CPA_DOC} {'found' if exists else 'not found'}",
        )

    def _check_owner_acceptance(self) -> PrerequisiteCheck:
        """P4: owner_paper_acceptance.json accepted=True (or waived)"""
        required = not self.waive_acceptance
        data = self._read_json(self._OWNER_ACCEPTANCE)
        if data is None:
            return PrerequisiteCheck(
                name="owner_acceptance",
                passed=False,
                required=required,
                notes="owner_paper_acceptance.json not found or malformed"
                      + (" (waived)" if self.waive_acceptance else ""),
            )
        accepted = bool(data.get("accepted", False))
        owner = data.get("owner") or ""
        return PrerequisiteCheck(
            name="owner_acceptance",
            passed=accepted,
            required=required,
            notes=(
                f"accepted by {owner}" if accepted
                else "not signed" + (" (waived)" if self.waive_acceptance else "")
            ),
        )

    def _check_kill_switch(self) -> PrerequisiteCheck:
        """P5: kill_switch_status.json triggered=False"""
        data = self._read_json(self._KILL_SWITCH)
        if data is None:
            # Missing file = unknown; treat as passing with a warning note
            return PrerequisiteCheck(
                name="kill_switch",
                passed=True,
                required=False,
                notes="kill_switch_status.json not found — assuming not triggered",
            )
        triggered = bool(data.get("triggered", False))
        reason = data.get("reason", "")
        return PrerequisiteCheck(
            name="kill_switch",
            passed=not triggered,
            required=True,
            notes=f"triggered={triggered}" + (f", reason={reason}" if triggered else ""),
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def check_prerequisites(self) -> List[PrerequisiteCheck]:
        """Return a list of all PrerequisiteCheck objects."""
        return [
            self._check_backtest_gate(),
            self._check_pre_paper_gate(),
            self._check_cpa_doc(),
            self._check_owner_acceptance(),
            self._check_kill_switch(),
        ]

    def can_kickoff(self) -> bool:
        """True only if all required prerequisites pass."""
        checks = self.check_prerequisites()
        return all(c.passed for c in checks if c.required)

    def kickoff(self, dry_run: bool = False) -> KickoffResult:
        """
        Execute kickoff if prerequisites pass.

        Args:
            dry_run: If True, validates prerequisites but does NOT write any files.

        Returns:
            KickoffResult with success=True if kicked off (or would be in dry_run).
        """
        checks = self.check_prerequisites()
        blocking_issues: List[str] = []
        warnings: List[str] = []

        for c in checks:
            if c.required and not c.passed:
                blocking_issues.append(f"{c.name}: {c.notes}")
            elif not c.required and not c.passed:
                warnings.append(f"{c.name}: {c.notes}")

        success = len(blocking_issues) == 0
        now = datetime.now(timezone.utc)
        start_date = now.date().isoformat()

        if not success:
            return KickoffResult(
                success=False,
                start_date=start_date,
                day_zero=False,
                prerequisites=checks,
                blocking_issues=blocking_issues,
                warnings=warnings,
                receipt_path=None,
            )

        receipt_path: Optional[str] = None

        if not dry_run:
            self._create_paper_state(start_date)
            result_partial = KickoffResult(
                success=True,
                start_date=start_date,
                day_zero=True,
                prerequisites=checks,
                blocking_issues=blocking_issues,
                warnings=warnings,
                receipt_path=None,
            )
            receipt_path = self._create_receipt(result_partial)

        return KickoffResult(
            success=True,
            start_date=start_date,
            day_zero=True,
            prerequisites=checks,
            blocking_issues=blocking_issues,
            warnings=warnings,
            receipt_path=receipt_path,
        )

    def _create_paper_state(self, start_date: str) -> str:
        """Create data/paper/paper_state.json. Returns absolute path."""
        now_iso = datetime.now(timezone.utc).isoformat()
        state = {
            "schema_version": "1.0",
            "start_date": start_date,
            "day": 0,
            "status": "running",
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        return self._atomic_write(self._PAPER_STATE, state)

    def _create_receipt(self, result: KickoffResult) -> str:
        """Create data/paper/kickoff_receipt.json. Returns absolute path."""
        now_iso = datetime.now(timezone.utc).isoformat()
        receipt = {
            "schema_version": "1.0",
            "kickoff_at": now_iso,
            "start_date": result.start_date,
            "day_zero": result.day_zero,
            "waive_acceptance": self.waive_acceptance,
            "prerequisites": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "required": c.required,
                    "notes": c.notes,
                }
                for c in result.prerequisites
            ],
            "blocking_issues": result.blocking_issues,
            "warnings": result.warnings,
        }
        return self._atomic_write(self._RECEIPT, receipt)

    def status(self) -> dict:
        """
        Return current paper trading status.

        Returns a dict with ``status`` equal to one of:
          - ``"not_started"``  — data/paper/paper_state.json does not exist
          - ``"running"``      — paper_state.json exists and status == "running"
          - ``"completed"``    — paper_state.json exists and status == "completed"
        """
        data = self._read_json(self._PAPER_STATE)
        if data is None:
            return {"status": "not_started", "paper_state": None}
        inner_status = data.get("status", "running")
        return {
            "status": inner_status,
            "start_date": data.get("start_date"),
            "day": data.get("day", 0),
            "paper_state": data,
        }


# ── CLI ───────────────────────────────────────────────────────────────────────

def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="MP-1355: Paper Trading Kickoff — validate prerequisites and start paper period",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Check prerequisites only (no kickoff)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate prerequisites and simulate kickoff without writing files",
    )
    parser.add_argument(
        "--base-dir", default=".",
        help="Repository root (default: current directory)",
    )
    parser.add_argument(
        "--waive-acceptance", action="store_true",
        help="Allow kickoff without signed owner acceptance",
    )
    args = parser.parse_args(argv)

    kickoff = PaperTradingKickoff(
        base_dir=args.base_dir,
        waive_acceptance=args.waive_acceptance,
    )

    if args.check:
        checks = kickoff.check_prerequisites()
        print("Prerequisites:")
        for c in checks:
            mark = "✓" if c.passed else ("✗" if c.required else "!")
            req = "[required]" if c.required else "[optional]"
            print(f"  {mark} {c.name} {req}: {c.notes}")
        print()
        can = kickoff.can_kickoff()
        print(f"can_kickoff: {can}")
        return 0 if can else 1

    result = kickoff.kickoff(dry_run=args.dry_run)

    prefix = "[DRY RUN] " if args.dry_run else ""
    if result.success:
        print(f"{prefix}Kickoff SUCCESS — paper trading starts {result.start_date}")
        if result.receipt_path:
            print(f"  Receipt: {result.receipt_path}")
    else:
        print(f"{prefix}Kickoff BLOCKED")
        for issue in result.blocking_issues:
            print(f"  ✗ {issue}")

    if result.warnings:
        print("Warnings:")
        for w in result.warnings:
            print(f"  ! {w}")

    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(_main())
