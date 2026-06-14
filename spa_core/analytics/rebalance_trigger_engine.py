"""Rebalance Trigger Engine — MP-652.

Determines whether the portfolio needs rebalancing based on drift from
target allocations and APY changes.

Design constraints
------------------
* Pure stdlib only — no external dependencies.
* Advisory / read-only — never touches allocator / risk / execution.
* Atomic writes: tmp-file + os.replace on every save.
* Ring-buffer: data/rebalance_triggers.json capped at MAX_ENTRIES=100.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATA_FILE = Path("data/rebalance_triggers.json")
MAX_ENTRIES = 100

# Trigger thresholds
DRIFT_THRESHOLD_PCT = 0.05      # 5% drift from target triggers rebalance check
APY_CHANGE_THRESHOLD = 0.02     # 2% APY change triggers review
MIN_DAYS_BETWEEN_REBALANCE = 7  # don't rebalance more often than weekly


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AllocationSlot:
    """Represents one adapter's allocation state."""
    adapter_id: str
    target_pct: float    # 0.0-1.0 target allocation
    current_pct: float   # 0.0-1.0 actual allocation
    current_apy: float   # current APY (e.g. 0.05 = 5%)
    prev_apy: float      # APY from last rebalance check
    days_since_last: int # days since last rebalance


@dataclass
class RebalanceTrigger:
    """Output of a single rebalance evaluation."""
    timestamp: float
    triggered: bool
    reason: str                  # WHY it triggered (or "NO_TRIGGER" / "NO_SLOTS" / "COOLDOWN")
    drifted_slots: List[str]     # adapter_ids with drift >= drift_threshold
    apy_changed_slots: List[str] # adapter_ids with APY change >= apy_threshold
    max_drift: float             # maximum absolute drift across all slots
    total_drift: float           # sum of absolute drifts across all slots
    urgency: str                 # IMMEDIATE / SOON / NONE
    actions: List[str]           # list of recommended human-readable actions


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class RebalanceTriggerEngine:
    """Evaluate portfolio slots and decide whether rebalancing is needed."""

    def __init__(
        self,
        data_file: Path = DATA_FILE,
        drift_threshold: float = DRIFT_THRESHOLD_PCT,
        apy_threshold: float = APY_CHANGE_THRESHOLD,
        min_days: int = MIN_DAYS_BETWEEN_REBALANCE,
    ) -> None:
        self.data_file = data_file
        self.drift_threshold = drift_threshold
        self.apy_threshold = apy_threshold
        self.min_days = min_days

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _drift(self, slot: AllocationSlot) -> float:
        """Absolute drift of one slot from its target."""
        return abs(slot.current_pct - slot.target_pct)

    def _apy_change(self, slot: AllocationSlot) -> float:
        """Absolute APY change for one slot since last check."""
        return abs(slot.current_apy - slot.prev_apy)

    def _drifted(self, slots: List[AllocationSlot]) -> List[str]:
        """Return adapter_ids whose drift meets or exceeds the threshold."""
        return [s.adapter_id for s in slots if self._drift(s) >= self.drift_threshold]

    def _apy_changed(self, slots: List[AllocationSlot]) -> List[str]:
        """Return adapter_ids whose APY change meets or exceeds the threshold."""
        return [s.adapter_id for s in slots if self._apy_change(s) >= self.apy_threshold]

    def _max_drift(self, slots: List[AllocationSlot]) -> float:
        """Maximum absolute drift across all slots (0.0 if slots is empty)."""
        if not slots:
            return 0.0
        return max(self._drift(s) for s in slots)

    def _total_drift(self, slots: List[AllocationSlot]) -> float:
        """Sum of absolute drifts across all slots."""
        return sum(self._drift(s) for s in slots)

    def _urgency(self, max_drift: float, drifted_count: int) -> str:
        """
        Classify urgency of a rebalance need.

        IMMEDIATE: max_drift >= 15% OR >= 3 slots drifted
        SOON:      max_drift >= 5%  OR >= 1 slot drifted
        NONE:      otherwise
        """
        if max_drift >= 0.15 or drifted_count >= 3:
            return "IMMEDIATE"
        if max_drift >= 0.05 or drifted_count >= 1:
            return "SOON"
        return "NONE"

    def _actions(
        self,
        drifted: List[str],
        apy_changed: List[str],
        urgency: str,
    ) -> List[str]:
        """Build a list of recommended actions based on findings."""
        actions: List[str] = []

        if drifted:
            actions.append(
                f"Rebalance {len(drifted)} slot(s): {', '.join(drifted)}"
            )
        if apy_changed:
            actions.append(
                f"Review APY for {len(apy_changed)} adapter(s): {', '.join(apy_changed)}"
            )
        if urgency == "IMMEDIATE":
            actions.append("Execute rebalance within 24h")
        elif urgency == "SOON":
            actions.append("Schedule rebalance within 7 days")

        if not actions:
            actions.append("No action required")

        return actions

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, slots: List[AllocationSlot]) -> RebalanceTrigger:
        """
        Evaluate the current portfolio state and return a RebalanceTrigger.

        Short-circuits:
        * Empty slots → triggered=False, reason="NO_SLOTS"
        * Cooldown active (min days_since_last < min_days) → triggered=False, reason="COOLDOWN ..."
        """
        if not slots:
            return RebalanceTrigger(
                timestamp=time.time(),
                triggered=False,
                reason="NO_SLOTS",
                drifted_slots=[],
                apy_changed_slots=[],
                max_drift=0.0,
                total_drift=0.0,
                urgency="NONE",
                actions=["No slots to evaluate"],
            )

        # Cooldown: use the minimum days_since_last across all slots
        min_days_seen = min(s.days_since_last for s in slots)
        if min_days_seen < self.min_days:
            return RebalanceTrigger(
                timestamp=time.time(),
                triggered=False,
                reason=f"COOLDOWN ({min_days_seen}d < {self.min_days}d minimum)",
                drifted_slots=[],
                apy_changed_slots=[],
                max_drift=self._max_drift(slots),
                total_drift=self._total_drift(slots),
                urgency="NONE",
                actions=["Cooldown active — skip rebalance"],
            )

        drifted = self._drifted(slots)
        apy_changed = self._apy_changed(slots)
        max_d = self._max_drift(slots)
        total_d = self._total_drift(slots)

        triggered = bool(drifted or apy_changed)

        if drifted and apy_changed:
            reason = "DRIFT_AND_APY_CHANGE"
        elif drifted:
            reason = "ALLOCATION_DRIFT"
        elif apy_changed:
            reason = "APY_CHANGE"
        else:
            reason = "NO_TRIGGER"

        urgency = self._urgency(max_d, len(drifted)) if triggered else "NONE"
        actions = self._actions(drifted, apy_changed, urgency)

        return RebalanceTrigger(
            timestamp=time.time(),
            triggered=triggered,
            reason=reason,
            drifted_slots=drifted,
            apy_changed_slots=apy_changed,
            max_drift=round(max_d, 6),
            total_drift=round(total_d, 6),
            urgency=urgency,
            actions=actions,
        )

    def save_trigger(self, trigger: RebalanceTrigger) -> None:
        """Atomically append the trigger to the ring-buffer JSON file."""
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing: list = json.loads(self.data_file.read_text())
        except Exception:
            existing = []

        existing.append(
            {
                "timestamp": trigger.timestamp,
                "triggered": trigger.triggered,
                "reason": trigger.reason,
                "urgency": trigger.urgency,
                "max_drift": trigger.max_drift,
            }
        )
        existing = existing[-MAX_ENTRIES:]

        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        """Return the full history list from the JSON file, or [] on any error."""
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []
