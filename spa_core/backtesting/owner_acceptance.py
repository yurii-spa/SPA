"""
spa_core/backtesting/owner_acceptance.py

Owner acceptance workflow for paper trading launch.
Before paper trading can start, the owner must explicitly accept:
  1. Pre-paper backtest gate is PASS
  2. Research exclusions are understood
  3. Paper period parameters are set
  4. Risk is acknowledged

This module:
  - Validates all gate prerequisites
  - Generates an acceptance draft (data/backtest/owner_paper_acceptance_draft.json)
  - Provides signing workflow (write to owner_paper_acceptance.json)
  - Is immutable once signed

MP-1309 (v9.25) — stdlib only, atomic writes, no external dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Optional

# Ensure repo root is on sys.path so relative imports work regardless of cwd
_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ── Constants ──────────────────────────────────────────────────────────────────

# Strict-only strategies eligible during paper period.
# S8 (Delta-Neutral sUSDe), S9 (E-Mode Looping), S10 (Pendle YT) are
# paper-only advisory during this phase per ADR-021.
_STRICT_STRATEGIES: list[str] = [
    "S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7"
]

_RISK_STATEMENT: str = (
    "Paper trading uses virtual capital of $100,000 USDC. No real funds are at risk. "
    "All allocation decisions pass through the deterministic RiskPolicy (v1.0). "
    "The owner acknowledges that historical backtest results do not guarantee future "
    "performance. Research exclusions listed in this acceptance represent protocols "
    "excluded from the strict backtest scope and must not be allocated during the "
    "paper period without a separate ADR. The 30-day gap-free paper track is required "
    "before any live trading decision (ADR-002). LLM agents are forbidden in risk, "
    "execution, and monitoring components (LLM_FORBIDDEN_AGENTS policy). "
    "RiskPolicy approved=False cannot be overridden by any agent or strategy."
)


# ── Main class ─────────────────────────────────────────────────────────────────

class OwnerAcceptanceWorkflow:
    """
    Formalises owner sign-off before paper trading launch.

    Usage::

        workflow = OwnerAcceptanceWorkflow()

        # Check what's needed
        prereqs = workflow.check_prerequisites()
        if not prereqs["all_met"]:
            print("Missing:", prereqs["missing"])

        # Generate a draft for review
        draft = workflow.generate_draft()

        # Sign when ready
        acceptance = workflow.sign(owner_name="Alice")
        print(workflow.is_signed())  # True

        # Revoke if parameters change materially
        workflow.revoke(reason="Strategy scope updated after ADR-022")
    """

    # Class-level default paths (relative to cwd / repo root)
    ACCEPTANCE_PATH = "data/backtest/owner_paper_acceptance.json"
    DRAFT_PATH = "data/backtest/owner_paper_acceptance_draft.json"

    # Gate file names inside backtest_dir
    _PRE_PAPER_GATE_FILE = "pre_paper_backtest_gate.json"

    def __init__(self, backtest_dir: str = "data/backtest") -> None:
        """
        Args:
            backtest_dir: Directory containing gate JSON files.
                          Defaults to "data/backtest" (relative to cwd).
        """
        self._dir = Path(backtest_dir)
        self._acceptance_path = self._dir / "owner_paper_acceptance.json"
        self._draft_path = self._dir / "owner_paper_acceptance_draft.json"
        self._pre_paper_path = self._dir / self._PRE_PAPER_GATE_FILE

    # ── Public API ─────────────────────────────────────────────────────────────

    def check_prerequisites(self) -> dict:
        """
        Validates all prerequisites required before signing.

        Returns::

            {
                "pre_paper_gate": "PASS" | "FAIL" | "UNKNOWN",
                "source_pipeline_ready": bool,
                "all_met": bool,
                "missing": ["list of unmet prerequisite descriptions"]
            }

        Notes:
            - pre_paper_gate must be "PASS"
            - source_pipeline_ready is True when paper_test_can_be_designed=True
              in the pre-paper gate file
            - all_met is True only when both above conditions hold
        """
        pre_data = self._load_json(self._pre_paper_path)
        missing: list[str] = []

        if pre_data is None:
            pre_gate = "FAIL"
            source_pipeline_ready = False
            missing.append(
                f"{self._PRE_PAPER_GATE_FILE} not found or invalid — "
                "run the pre-paper backtest gate first"
            )
        else:
            raw_status = pre_data.get("status", "UNKNOWN")
            pre_gate = raw_status if raw_status in ("PASS", "FAIL") else "UNKNOWN"
            if pre_gate != "PASS":
                missing.append(
                    f"Pre-paper backtest gate is '{pre_gate}' (must be PASS)"
                )
            source_pipeline_ready = bool(
                pre_data.get("paper_test_can_be_designed", False)
            )
            if not source_pipeline_ready:
                missing.append(
                    "paper_test_can_be_designed is False — "
                    "source pipeline must be ready before owner acceptance"
                )

        all_met = (pre_gate == "PASS") and source_pipeline_ready

        return {
            "pre_paper_gate": pre_gate,
            "source_pipeline_ready": source_pipeline_ready,
            "all_met": all_met,
            "missing": missing,
        }

    def generate_draft(self, paper_params: Optional[dict] = None) -> dict:
        """
        Creates an acceptance draft and saves it to DRAFT_PATH atomically.

        The draft captures the current prerequisites snapshot, research
        exclusions from the pre-paper gate, and proposed paper parameters.
        The owner reviews and edits this file before calling sign().

        Args:
            paper_params: Optional overrides for paper period parameters:
                {
                  "paper_period_days": int,   # default 90
                  "initial_capital": float,   # default 100_000
                  "strategy_scope": [str],    # default _STRICT_STRATEGIES
                }

        Returns:
            The draft dict (also written atomically to DRAFT_PATH).
        """
        if paper_params is None:
            paper_params = {}

        prereqs = self.check_prerequisites()

        # Collect research exclusions from the pre-paper gate file
        pre_data = self._load_json(self._pre_paper_path) or {}
        exclusions_raw: list[dict] = pre_data.get("research_exclusions", [])
        exclusion_ids: list[str] = [
            e.get("protocol_id", "")
            for e in exclusions_raw
            if e.get("protocol_id")
        ]

        # Blockers: anything that would prevent signing
        blockers: list[str] = list(prereqs["missing"])

        draft: dict = {
            "schema_version": "0.1",
            "generated_at": date.today().isoformat(),
            "owner": None,
            "accepted": False,
            "paper_period_days": int(
                paper_params.get("paper_period_days", 90)
            ),
            "initial_capital": float(
                paper_params.get("initial_capital", 100_000)
            ),
            "strategy_scope": list(
                paper_params.get("strategy_scope", _STRICT_STRATEGIES)
            ),
            "research_exclusions_acknowledged": exclusion_ids,
            "risk_statement": _RISK_STATEMENT,
            "blockers": blockers,
            "prerequisites": prereqs,
        }

        # Atomic write: tmp → replace
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._draft_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(draft, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(self._draft_path))

        return draft

    def sign(
        self,
        owner_name: str,
        paper_params: Optional[dict] = None,
    ) -> dict:
        """
        Validates prerequisites, generates and saves a signed acceptance.

        The acceptance file (ACCEPTANCE_PATH) is written atomically.
        Once signed, calling sign() again raises ValueError (immutability).
        Use revoke() first if parameters must change materially.

        Args:
            owner_name: Display name of the owner signing the acceptance.
            paper_params: Optional paper period parameter overrides (same
                          keys as generate_draft()).

        Returns:
            The signed acceptance dict.

        Raises:
            ValueError: If already signed (immutability violation).
            ValueError: If prerequisites are not met.
        """
        # ── Immutability guard ─────────────────────────────────────────────
        existing = self._load_json(self._acceptance_path)
        if existing is not None and existing.get("accepted", False):
            raise ValueError(
                "Owner acceptance is already signed and is immutable. "
                "Call revoke(reason=...) before re-signing."
            )

        # ── Prerequisites check ────────────────────────────────────────────
        prereqs = self.check_prerequisites()
        if not prereqs["all_met"]:
            raise ValueError(
                f"Cannot sign: prerequisites not met — {prereqs['missing']}"
            )

        if paper_params is None:
            paper_params = {}

        # Collect research exclusions
        pre_data = self._load_json(self._pre_paper_path) or {}
        exclusions_raw: list[dict] = pre_data.get("research_exclusions", [])
        exclusion_ids: list[str] = [
            e.get("protocol_id", "")
            for e in exclusions_raw
            if e.get("protocol_id")
        ]

        today = date.today().isoformat()
        acceptance: dict = {
            "schema_version": "0.1",
            "generated_at": today,
            "accepted_at": today,
            "owner": owner_name,
            "accepted": True,
            "paper_period_days": int(
                paper_params.get("paper_period_days", 90)
            ),
            "initial_capital": float(
                paper_params.get("initial_capital", 100_000)
            ),
            "strategy_scope": list(
                paper_params.get("strategy_scope", _STRICT_STRATEGIES)
            ),
            "research_exclusions_acknowledged": exclusion_ids,
            "risk_statement": _RISK_STATEMENT,
            "blockers": [],
            "prerequisites": prereqs,
        }

        # Atomic write
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._acceptance_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(acceptance, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(self._acceptance_path))

        return acceptance

    def is_signed(self) -> bool:
        """
        Returns True if the acceptance file exists and accepted=True.
        """
        data = self._load_json(self._acceptance_path)
        if data is None:
            return False
        return bool(data.get("accepted", False))

    def acceptance_status(self) -> dict:
        """
        Returns current acceptance status for gate.py integration.

        Returns::

            {
                "signed": bool,
                "owner": str | None,
                "accepted_at": str | None,
                "gate_status": "NOT_SIGNED" | "SIGNED" | "REVOKED",
                "paper_period_days": int | None,
                "initial_capital": float | None,
                "strategy_scope": list | None,
            }
        """
        data = self._load_json(self._acceptance_path)
        if data is None:
            return {
                "signed": False,
                "owner": None,
                "accepted_at": None,
                "gate_status": "NOT_SIGNED",
                "paper_period_days": None,
                "initial_capital": None,
                "strategy_scope": None,
            }

        signed = bool(data.get("accepted", False))
        if signed:
            gate_status = "SIGNED"
        elif data.get("revoke_reason"):
            gate_status = "REVOKED"
        else:
            gate_status = "NOT_SIGNED"

        return {
            "signed": signed,
            "owner": data.get("owner"),
            "accepted_at": data.get("accepted_at"),
            "gate_status": gate_status,
            "paper_period_days": data.get("paper_period_days"),
            "initial_capital": data.get("initial_capital"),
            "strategy_scope": data.get("strategy_scope"),
        }

    def revoke(self, reason: str) -> None:
        """
        Revokes a signed acceptance (e.g. if strategy scope changes materially).

        Sets accepted=False and records revoke_reason + revoked_at.
        After revocation, sign() can be called again.

        If no acceptance file exists, this is a no-op (safe to call).

        Args:
            reason: Human-readable explanation for the revocation.
        """
        data = self._load_json(self._acceptance_path)
        if data is None:
            return  # No-op — nothing to revoke

        data["accepted"] = False
        data["revoked_at"] = date.today().isoformat()
        data["revoke_reason"] = reason

        tmp = self._acceptance_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(self._acceptance_path))

    # ── Private helpers ────────────────────────────────────────────────────────

    def _load_json(self, path: Path) -> Optional[dict]:
        """Load and parse a JSON file. Returns None on any error."""
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None


# ── CLI ────────────────────────────────────────────────────────────────────────

def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Owner Acceptance Workflow — paper trading launch sign-off",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 -m spa_core.backtesting.owner_acceptance --generate-draft\n"
            "  python3 -m spa_core.backtesting.owner_acceptance --status\n"
        ),
    )
    parser.add_argument(
        "--generate-draft",
        action="store_true",
        help="Generate acceptance draft and print to stdout",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print current acceptance status",
    )
    parser.add_argument(
        "--backtest-dir",
        default="data/backtest",
        help="Path to backtest directory (default: data/backtest)",
    )
    args = parser.parse_args()

    workflow = OwnerAcceptanceWorkflow(backtest_dir=args.backtest_dir)

    if args.generate_draft:
        draft = workflow.generate_draft()
        print(json.dumps(draft, indent=2))
    elif args.status:
        status = workflow.acceptance_status()
        print(json.dumps(status, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    _main()
