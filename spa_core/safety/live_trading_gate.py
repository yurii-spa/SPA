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
import time
from typing import Optional

from spa_core.utils.errors import LiveTradingForbiddenError
from spa_core.utils.atomic import atomic_save

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
    """Shim — delegates to spa_core.utils.atomic.atomic_save."""
    atomic_save(data, path)


# ---------------------------------------------------------------------------
# LiveTradingGate — singleton-like gate controlling access to live trading
# ---------------------------------------------------------------------------

class LiveTradingGate:
    """
    Controls access to live trading.

    Gate is LOCKED by default. Activation requires:
    1. All prerequisite flags set (owner_acceptance, paper_trading_complete,
       pre_launch_validation) — set by external modules.
    2. Explicit activate() call with valid SHA256 activation_key.

    Raises LiveTradingForbiddenError if live trading is not authorised.
    All state is persisted atomically to data/live_trading_gate.json.

    LLM_FORBIDDEN: no LLM calls here.
    MP-1401 (v10.17) — stdlib only.
    """

    def __init__(self, base_dir: str = ".") -> None:
        self.base_dir = base_dir
        self._gate_path = os.path.join(base_dir, GATE_FILE)
        self._state: Optional[dict] = None

    # ── Internal helpers ────────────────────────────────────────────────────

    def _load(self) -> dict:
        """Load gate state from file. Returns default LOCKED state if missing or corrupt."""
        if os.path.exists(self._gate_path):
            try:
                with open(self._gate_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    state = dict(_DEFAULT_STATE)
                    state.update(data)
                    return state
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning(
                    "live_trading_gate: corrupt state file, defaulting to LOCKED: %s", exc
                )
        # Missing or corrupt — start locked
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

    # ── Public API ──────────────────────────────────────────────────────────

    def is_active(self) -> bool:
        """True only if the gate has been explicitly activated."""
        return bool(self._state_loaded().get("active", False))

    def require_live_gate(self) -> None:
        """
        Hard gate — raises LiveTradingForbiddenError if not active.

        This check cannot be bypassed by configuration or env vars.

        Raises:
            LiveTradingForbiddenError: if the gate is LOCKED.
        """
        if not self.is_active():
            raise LiveTradingForbiddenError("live_trading_gate")

    def get_prerequisites(self) -> dict:
        """Return current prerequisite status dict."""
        state = self._state_loaded()
        owner_acceptance       = bool(state.get("owner_acceptance", False))
        paper_trading_complete = bool(state.get("paper_trading_complete", False))
        pre_launch_validation  = bool(state.get("pre_launch_validation", False))
        manually_activated     = bool(state.get("active", False))
        all_met = (
            owner_acceptance
            and paper_trading_complete
            and pre_launch_validation
            and manually_activated
        )
        return {
            "owner_acceptance":       owner_acceptance,
            "paper_trading_complete": paper_trading_complete,
            "pre_launch_validation":  pre_launch_validation,
            "manually_activated":     manually_activated,
            "all_met":                all_met,
        }

    def activate(self, activation_key: str, reason: str) -> bool:
        """
        Activate live trading if all prerequisites are met.

        Returns False (keeps gate LOCKED) if activation_key is not a valid
        SHA256 hex digest or if any prerequisite flag is missing.

        Args:
            activation_key: SHA256 hex digest (64 chars) of the signed acceptance doc.
            reason:         Human-readable reason (logged and persisted).

        Returns:
            True if activated, False otherwise.
        """
        state = self._state_loaded()
        if not _is_valid_sha256(activation_key):
            logger.warning("live_trading_gate.activate: invalid activation_key format")
            return False
        if not state.get("owner_acceptance", False):
            logger.warning("live_trading_gate.activate: owner_acceptance not met")
            return False
        if not state.get("paper_trading_complete", False):
            logger.warning("live_trading_gate.activate: paper_trading_complete not met")
            return False
        if not state.get("pre_launch_validation", False):
            logger.warning("live_trading_gate.activate: pre_launch_validation not met")
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
        Emergency deactivation. Idempotent — deactivating a LOCKED gate is a no-op.

        Args:
            reason: Human-readable reason (logged and persisted).
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
        """Return human-readable gate status string."""
        state = self._state_loaded()
        active = bool(state.get("active", False))
        prereqs = self.get_prerequisites()
        label = "ACTIVE" if active else "BLOCKED"
        lines = [
            f"LiveTradingGate status: {label}",
            f"  owner_acceptance:       {prereqs['owner_acceptance']}",
            f"  paper_trading_complete: {prereqs['paper_trading_complete']}",
            f"  pre_launch_validation:  {prereqs['pre_launch_validation']}",
            f"  manually_activated:     {prereqs['manually_activated']}",
            f"  all_met:                {prereqs['all_met']}",
        ]
        if active:
            lines.append(f"  activated_at:     {state.get('activated_at', 'unknown')}")
            lines.append(f"  activated_reason: {state.get('activated_reason', '')}")
        else:
            missing = [k for k, v in prereqs.items() if k != "all_met" and not v]
            if missing:
                lines.append(f"  missing prerequisites: {', '.join(missing)}")
        return "\n".join(lines)


# ── Module-level singleton ──────────────────────────────────────────────────

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
