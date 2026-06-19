"""
spa_core/safety/live_trading_gate.py

Central enforcement of the LIVE TRADING IS FORBIDDEN constraint.
All code that could execute real trades MUST call require_live_gate() first.

The gate is OFF by default. Manual activation requires:
1. Owner acceptance signed (OwnerAcceptance module) — owner_acceptance flag
2. Paper trading period completed (>= 30 evidence points) — paper_trading_complete flag
3. Pre-launch validation PASS (all 38 checks) — pre_launch_validation flag
4. Explicit gate activation via activate() with valid SHA256 activation_key

The gate state is stored in data/live_trading_gate.json (NOT in KANBAN).
All writes are atomic: tmp + os.replace.

LLM_FORBIDDEN: no LLM calls inside this module — prompt injection in capital is
a critical attack vector.

MP-1401 (v10.17) — stdlib only, no external dependencies.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from typing import Optional

from spa_core.utils.errors import LiveTradingForbiddenError

__all__ = [
    "LiveTradingGate",
    "require_live_gate",
]

logger = logging.getLogger("spa.safety.live_trading_gate")

GATE_FILE = "data/live_trading_gate.json"

_DEFAULT_STATE: dict = {
    "active": False,
    "activation_key_hash": None,
    "activated_at": None,
    "activated_reason": None,
    "deactivated_at": None,
    "deactivated_reason": None,
    # Prerequisites — set by external modules (OwnerAcceptance, GoLiveChecker, etc.)
    "owner_acceptance": False,
    "paper_trading_complete": False,
    "pre_launch_validation": False,
    "schema_version": 1,
}


def _is_valid_sha256(key: str) -> bool:
    """Return True if *key* is a 64-character lowercase hex string (SHA-256 digest)."""
    if not isinstance(key, str):
        return False
    if len(key) != 64:
        return False
    try:
        int(key, 16)
        return True
    except ValueError:
        return False


def _atomic_write(path: str, data: dict) -> None:
    """Write *data* as JSON to *path* atomically (tmp + os.replace)."""
    dir_ = os.path.dirname(path) or "."
    os.makedirs(dir_, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_, prefix=".live_trading_gate_tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


class LiveTradingGate:
    """
    Singleton-like gate that controls access to live trading.

    The gate is LOCKED by default and can only be activated when ALL
    prerequisites are met AND a valid activation_key (SHA256 of the owner
    acceptance document) is provided.

    Raises LiveTradingForbiddenError if live trading is not authorised.

    Usage::

        gate = LiveTradingGate()
        gate.require_live_gate()   # raises if LOCKED

        # To activate (only after all prerequisites are met):
        gate.activate(activation_key="<sha256>", reason="Go-live 2026-08-01")
    """

    def __init__(self, base_dir: str = ".") -> None:
        self.base_dir = base_dir
        self._gate_path = os.path.join(base_dir, GATE_FILE)
        self._state: Optional[dict] = None

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _load(self) -> dict:
        """Load gate state from file.  Returns default LOCKED state if missing or corrupt."""
        if os.path.exists(self._gate_path):
            try:
                with open(self._gate_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    # Merge with defaults so new fields are always present
                    state = dict(_DEFAULT_STATE)
                    state.update(data)
                    return state
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("live_trading_gate: corrupt state file, defaulting to LOCKED: %s", exc)
        # File missing or corrupt — start locked, persist immediately
        state = dict(_DEFAULT_STATE)
        try:
            _atomic_write(self._gate_path, state)
        except OSError as exc:
            logger.warning("live_trading_gate: could not write default state: %s", exc)
        return state

    def _state_loaded(self) -> dict:
        """Return cached state, loading from disk if necessary."""
        if self._state is None:
            self._state = self._load()
        return self._state

    def _save(self) -> None:
        """Persist current in-memory state atomically."""
        if self._state is None:
            return
        _atomic_write(self._gate_path, self._state)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def is_active(self) -> bool:
        """True only if the gate has been explicitly activated with all prerequisites met."""
        return bool(self._state_loaded().get("active", False))

    def require_live_gate(self) -> None:
        """
        Call this before any live trading operation.

        Raises:
            LiveTradingForbiddenError: if the gate is not active.

        This check is *hard*: it cannot be bypassed by configuration or
        environment variables.
        """
        if not self.is_active():
            raise LiveTradingForbiddenError("live_trading_gate")

    def get_prerequisites(self) -> dict:
        """
        Return the current prerequisite status.

        Returns a dict with keys::

            owner_acceptance:       bool  — owner has signed acceptance doc
            paper_trading_complete: bool  — >= 30 evidence days logged
            pre_launch_validation:  bool  — all 38 pre-launch checks PASS
            manually_activated:     bool  — gate explicitly activated
            all_met:                bool  — all four above are True

        External modules (OwnerAcceptance, GoLiveChecker) write directly
        to the gate state file to update the first three flags.
        """
        state = self._state_loaded()
        owner_acceptance = bool(state.get("owner_acceptance", False))
        paper_trading_complete = bool(state.get("paper_trading_complete", False))
        pre_launch_validation = bool(state.get("pre_launch_validation", False))
        manually_activated = bool(state.get("active", False))
        all_met = owner_acceptance and paper_trading_complete and pre_launch_validation and manually_activated
        return {
            "owner_acceptance": owner_acceptance,
            "paper_trading_complete": paper_trading_complete,
            "pre_launch_validation": pre_launch_validation,
            "manually_activated": manually_activated,
            "all_met": all_met,
        }

    def activate(self, activation_key: str, reason: str) -> bool:
        """
        Activate live trading.

        Returns False (and keeps gate LOCKED) if:
        - *activation_key* is not a valid SHA256 hex digest (64 hex chars)
        - Any prerequisite flag is missing (owner_acceptance, paper_trading_complete,
          pre_launch_validation)

        Returns True and persists the ACTIVE state if all checks pass.

        Args:
            activation_key: SHA256 hex digest of the signed owner acceptance document.
            reason:         Human-readable reason for activation (logged).
        """
        state = self._state_loaded()

        # Validate activation key format
        if not _is_valid_sha256(activation_key):
            logger.warning(
                "live_trading_gate.activate: invalid activation_key format (must be SHA256 hex)"
            )
            return False

        # Check prerequisites
        if not state.get("owner_acceptance", False):
            logger.warning("live_trading_gate.activate: owner_acceptance prerequisite not met")
            return False
        if not state.get("paper_trading_complete", False):
            logger.warning("live_trading_gate.activate: paper_trading_complete prerequisite not met")
            return False
        if not state.get("pre_launch_validation", False):
            logger.warning("live_trading_gate.activate: pre_launch_validation prerequisite not met")
            return False

        # All checks pass — activate
        state["active"] = True
        state["activation_key_hash"] = hashlib.sha256(activation_key.encode()).hexdigest()
        state["activated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        state["activated_reason"] = reason
        state["deactivated_at"] = None
        state["deactivated_reason"] = None
        self._state = state
        self._save()
        logger.info("live_trading_gate: ACTIVATED — reason: %s", reason)
        return True

    def deactivate(self, reason: str) -> None:
        """
        Emergency deactivation. The gate returns to LOCKED immediately.
        The deactivation reason and timestamp are persisted.

        This operation is idempotent — deactivating an already-LOCKED gate
        is a no-op (no error).

        Args:
            reason: Human-readable reason for deactivation (logged and persisted).
        """
        state = self._state_loaded()
        was_active = state.get("active", False)
        state["active"] = False
        state["deactivated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        state["deactivated_reason"] = reason
        self._state = state
        self._save()
        if was_active:
            logger.info("live_trading_gate: DEACTIVATED — reason: %s", reason)
        else:
            logger.debug("live_trading_gate: deactivate called on already-LOCKED gate (no-op)")

    def status_report(self) -> str:
        """
        Return a human-readable gate status string.

        Includes BLOCKED/ACTIVE status and prerequisite summary.
        """
        state = self._state_loaded()
        active = bool(state.get("active", False))
        prereqs = self.get_prerequisites()

        status_label = "ACTIVE" if active else "BLOCKED"

        lines = [
            f"LiveTradingGate status: {status_label}",
            f"  owner_acceptance:       {prereqs['owner_acceptance']}",
            f"  paper_trading_complete: {prereqs['paper_trading_complete']}",
            f"  pre_launch_validation:  {prereqs['pre_launch_validation']}",
            f"  manually_activated:     {prereqs['manually_activated']}",
            f"  all_met:                {prereqs['all_met']}",
        ]

        if active:
            activated_at = state.get("activated_at", "unknown")
            activated_reason = state.get("activated_reason", "")
            lines.append(f"  activated_at: {activated_at}")
            lines.append(f"  activated_reason: {activated_reason}")
        else:
            deactivated_reason = state.get("deactivated_reason")
            if deactivated_reason:
                lines.append(f"  deactivated_reason: {deactivated_reason}")
            missing = [k for k, v in prereqs.items() if k != "all_met" and not v]
            if missing:
                lines.append(f"  missing prerequisites: {', '.join(missing)}")

        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Module-level convenience function (singleton gate)
# ─────────────────────────────────────────────────────────────────────────────

_gate: Optional[LiveTradingGate] = None


def require_live_gate(base_dir: str = ".") -> None:
    """
    Module-level convenience wrapper around LiveTradingGate.require_live_gate().

    Uses a module-level singleton gate instance.

    Raises:
        LiveTradingForbiddenError: if the gate is not active.
    """
    global _gate
    if _gate is None:
        _gate = LiveTradingGate(base_dir)
    _gate.require_live_gate()
