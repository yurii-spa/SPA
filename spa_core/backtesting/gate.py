"""
SPA Backtesting — Gate System
==============================
MP-1301 (v9.17)

Reads the CPA backtest gate JSON files and provides a unified status
interface for the cycle_runner, dashboard, and operator tooling.

Files consumed (all under backtest_dir):
  pre_paper_backtest_gate.json   — historical backtest gate result
  paper_ready_gate.json          — paper-trading readiness composite
  owner_paper_acceptance_gate.json — owner sign-off status

All reads are defensive: missing / malformed files return UNKNOWN status
rather than raising exceptions. stdlib only, no external dependencies.
Reads only — never writes to any state file.
"""

from __future__ import annotations

import json
from pathlib import Path


class BacktestGate:
    """
    Reads CPA gate JSON files and provides gate status checks.

    The four states are:
      BACKTEST  → has the pre-paper historical backtest passed?
      PRE_PAPER → has the pre-paper gate (P0/P1A/P2) passed?
      PAPER     → is the system ready for paper trading?
      LIVE      → is live trading unblocked? (all gates + owner sign-off)

    Usage::

        gate = BacktestGate()

        status = gate.four_state_status()
        print(status["paper"])     # "NOT_READY"
        print(status["blockers"])  # ["Owner acceptance not signed", ...]

        allowed, reasons = gate.can_paper_trade()
    """

    # ── Gate file names ───────────────────────────────────────────────────────

    _PRE_PAPER_FILE = "pre_paper_backtest_gate.json"
    _PAPER_READY_FILE = "paper_ready_gate.json"
    _OWNER_FILE = "owner_paper_acceptance_gate.json"

    def __init__(self, backtest_dir: str = "data/backtest") -> None:
        """
        Args:
            backtest_dir: Path to the directory containing the gate JSON files.
                          Defaults to "data/backtest" (relative to cwd).
        """
        self._dir = Path(backtest_dir)

    # ── Public API ─────────────────────────────────────────────────────────────

    def pre_paper_status(self) -> dict:
        """
        Returns status of the pre-paper historical backtest gate.

        Returns::

            {
                "status": "PASS" | "FAIL" | "UNKNOWN",
                "gate": "pre_paper_backtest",
                "generated_at": "YYYY-MM-DD" | None,
                "paper_test_can_be_designed": bool,
                "paper_trading_allowed": bool,
                "warnings": [...],
                "strict_blockers": [...],
            }
        """
        data = self._load(self._PRE_PAPER_FILE)
        if data is None:
            return {
                "status": "UNKNOWN",
                "gate": "pre_paper_backtest",
                "generated_at": None,
                "paper_test_can_be_designed": False,
                "paper_trading_allowed": False,
                "warnings": [],
                "strict_blockers": [],
                "error": f"{self._PRE_PAPER_FILE} not found or invalid",
            }
        return {
            "status": data.get("status", "UNKNOWN"),
            "gate": "pre_paper_backtest",
            "generated_at": data.get("generated_at"),
            "paper_test_can_be_designed": bool(data.get("paper_test_can_be_designed", False)),
            "paper_trading_allowed": bool(data.get("paper_trading_allowed", False)),
            "warnings": data.get("warnings", []),
            "strict_blockers": data.get("strict_blockers", []),
        }

    def paper_ready_status(self) -> dict:
        """
        Returns composite paper-trading readiness status.

        Returns::

            {
                "status": "NOT_READY" | "READY" | "UNKNOWN",
                "gate": "paper_ready",
                "paper_trading_allowed": bool,
                "blockers": [...],
                "generated_at": "...",
                "run_id": "...",
            }
        """
        data = self._load(self._PAPER_READY_FILE)
        if data is None:
            return {
                "status": "UNKNOWN",
                "gate": "paper_ready",
                "paper_trading_allowed": False,
                "blockers": [f"{self._PAPER_READY_FILE} not found or invalid"],
                "generated_at": None,
                "run_id": None,
            }
        return {
            "status": data.get("status", "UNKNOWN"),
            "gate": "paper_ready",
            "paper_trading_allowed": bool(data.get("paper_trading_allowed", False)),
            "blockers": data.get("blockers", []),
            "generated_at": data.get("generated_at"),
            "run_id": data.get("run_id"),
        }

    def owner_acceptance_status(self) -> dict:
        """
        Returns owner sign-off status.

        Combines owner_paper_acceptance_gate.json (top-level) with the
        embedded owner_acceptance block inside paper_ready_gate.json.

        Returns::

            {
                "signed": bool,
                "owner": str | None,
                "signed_at": str | None,
                "gate_status": "NOT_SIGNED" | "SIGNED" | "UNKNOWN",
            }
        """
        # Primary: owner_acceptance block inside paper_ready_gate.json
        paper_data = self._load(self._PAPER_READY_FILE) or {}
        owner_acc = paper_data.get("owner_acceptance", {})

        signed = bool(owner_acc.get("accepted", False))
        owner = owner_acc.get("owner")
        signed_at = owner_acc.get("accepted_at")

        # Fallback / supplementary: owner gate file
        gate_data = self._load(self._OWNER_FILE) or {}
        gate_status = gate_data.get("status", "UNKNOWN")
        if gate_status == "NOT_SIGNED" and signed:
            # paper_ready says signed but gate file disagrees — gate wins
            signed = False

        return {
            "signed": signed,
            "owner": owner,
            "signed_at": signed_at,
            "gate_status": gate_status,
        }

    def four_state_status(self) -> dict:
        """
        Returns a 4-state panel suitable for dashboard display.

        The four states progress linearly: each gate must pass before the
        next can be READY.

        Returns::

            {
                "backtest":  "PASS" | "FAIL" | "UNKNOWN",
                "pre_paper": "PASS" | "FAIL" | "UNKNOWN",
                "paper":     "READY" | "NOT_READY" | "UNKNOWN",
                "live":      "READY" | "BLOCKED",
                "blockers":  [...],
            }
        """
        pre = self.pre_paper_status()
        paper = self.paper_ready_status()
        owner = self.owner_acceptance_status()

        blockers: list[str] = []

        # ── backtest state (from pre_paper gate) ──────────────────────────────
        bt_raw = pre.get("status", "UNKNOWN")
        backtest_state = bt_raw if bt_raw in ("PASS", "FAIL") else "UNKNOWN"

        # ── pre_paper state ───────────────────────────────────────────────────
        pre_paper_state = backtest_state  # same gate file

        # ── paper state ───────────────────────────────────────────────────────
        paper_raw = paper.get("status", "UNKNOWN")
        if paper_raw == "READY":
            paper_state = "READY"
        elif paper_raw == "NOT_READY":
            paper_state = "NOT_READY"
        else:
            paper_state = "UNKNOWN"

        # ── live state ────────────────────────────────────────────────────────
        paper_allowed = paper.get("paper_trading_allowed", False)
        owner_signed = owner.get("signed", False)

        live_state = "READY" if (paper_allowed and owner_signed) else "BLOCKED"

        if not owner_signed:
            blockers.append("Owner acceptance not signed")
        if not paper_allowed:
            for b in paper.get("blockers", []):
                if b not in blockers:
                    blockers.append(b)
        if backtest_state != "PASS":
            blockers.append("Pre-paper backtest gate not PASS")

        return {
            "backtest": backtest_state,
            "pre_paper": pre_paper_state,
            "paper": paper_state,
            "live": live_state,
            "blockers": blockers,
        }

    def can_paper_trade(self) -> tuple[bool, list[str]]:
        """
        Returns whether paper trading is currently allowed.

        Returns:
            (allowed: bool, reasons_if_blocked: list[str])

            allowed is True only when BOTH the pre-paper backtest gate is PASS
            AND the paper_ready gate allows paper trading.
        """
        pre = self.pre_paper_status()
        paper = self.paper_ready_status()

        reasons: list[str] = []
        pre_ok = pre.get("status") == "PASS"
        paper_ok = paper.get("paper_trading_allowed", False)

        if not pre_ok:
            reasons.append(
                f"Pre-paper backtest gate status is '{pre.get('status', 'UNKNOWN')}' (need PASS)"
            )
        if not paper_ok:
            for b in paper.get("blockers", []):
                reasons.append(b)

        allowed = pre_ok and paper_ok
        return allowed, reasons

    # ── Private helpers ────────────────────────────────────────────────────────

    def _load(self, filename: str) -> dict | None:
        """
        Load and parse a JSON gate file.

        Returns None if the file does not exist or cannot be parsed.
        """
        path = self._dir / filename
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            return None
        except OSError:
            return None
