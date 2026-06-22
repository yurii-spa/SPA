"""
spa_core/backtesting/launch_runbook.py

MP-1368 (v9.84) — Live Launch Runbook Automation.

Python module for tracking and automating the SPA live-launch runbook steps.
Maps onto LIVE_LAUNCH_RUNBOOK.md (docs/LIVE_LAUNCH_RUNBOOK.md).

Phases:
  pre_launch  — steps that must complete before T-Day
  launch      — capital deployment and strategy activation (T-Day)
  post_launch — post-deployment verification and monitoring setup

Rules:
  - stdlib only, no external dependencies
  - atomic save via tmp + os.replace
  - never modifies allocator/risk/execution state
  - completed state persists in data/live/launch_runbook_state.json
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Tuple

from spa_core.utils.atomic import atomic_save


# ── Constants ──────────────────────────────────────────────────────────────────

SCHEMA_VERSION = "1.0"

# (phase, step_id, description, blocking)
STEPS: List[Tuple[str, str, str, bool]] = [
    ("pre_launch",  "backup",        "Backup all config files",                     True),
    ("pre_launch",  "validate",      "Run pre_launch_validation",                   True),
    ("pre_launch",  "gnosis",        "Confirm Gnosis Safe address",                 True),
    ("launch",      "system_check",  "Run cpa_health_dashboard",                    True),
    ("launch",      "regime",        "Verify market regime",                        False),
    ("launch",      "capital",       "Deploy capital via Gnosis Safe",              True),
    ("launch",      "activate",      "Activate RS-001 slots",                       True),
    ("launch",      "notify",        "Send launch Telegram notification",           False),
    ("post_launch", "verify",        "Verify positions opened correctly",           True),
    ("post_launch", "monitoring",    "Set up daily monitoring",                     False),
]

VALID_PHASES = ("pre_launch", "launch", "post_launch", "completed")


# ── LaunchRunbook ──────────────────────────────────────────────────────────────

class LaunchRunbook:
    """
    Tracks the live launch runbook step completion.

    Usage::

        rb = LaunchRunbook()
        print(rb.current_phase())       # "pre_launch"
        print(rb.next_step())           # first uncompleted step dict
        rb.complete_step("backup", "Done: data/ copied to data_backup_20260801/")
        rb.complete_step("validate", "pre_launch_validation: LAUNCH_READY")
        rb.complete_step("gnosis", "Gnosis Safe 0xABC... confirmed")
        print(rb.can_proceed_to_launch())  # True (all blocking pre_launch done)
        print(rb.progress())               # {"pre_launch": {...}, "launch": {...}, ...}
        rb.save()
    """

    # ── Class-level step registry ──────────────────────────────────────────────
    STEPS = STEPS

    def __init__(
        self,
        runbook_path: str = "data/live/launch_runbook_state.json",
    ) -> None:
        self._path = Path(runbook_path)
        self._state: dict = self._load_state()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load_state(self) -> dict:
        """Load existing state defensively; return blank state on error."""
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict) and "completed_steps" in data:
                    return data
        except Exception:
            pass
        return {
            "schema_version": SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "completed_steps": {},  # step_id -> {completed_at, notes}
        }

    def save(self) -> None:
        """Atomic save to runbook_path using atomic_save."""
        self._state["updated_at"] = datetime.now(timezone.utc).isoformat()
        atomic_save(self._state, str(self._path))

    # ── Step helpers ───────────────────────────────────────────────────────────

    def _all_step_ids(self) -> List[str]:
        return [s[1] for s in STEPS]

    def _step_by_id(self, step_id: str) -> Optional[Tuple[str, str, str, bool]]:
        for s in STEPS:
            if s[1] == step_id:
                return s
        return None

    def _is_completed(self, step_id: str) -> bool:
        return step_id in self._state.get("completed_steps", {})

    # ── Public API ─────────────────────────────────────────────────────────────

    def complete_step(self, step_id: str, notes: str = "") -> None:
        """
        Mark a step as completed.

        Args:
            step_id: Must be a valid step_id from STEPS.
            notes:   Optional operator notes.

        Raises:
            ValueError: If step_id is not a known step.
        """
        step = self._step_by_id(step_id)
        if step is None:
            raise ValueError(
                f"Unknown step_id {step_id!r}. "
                f"Valid: {self._all_step_ids()}"
            )
        self._state.setdefault("completed_steps", {})[step_id] = {
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "notes": notes,
            "phase": step[0],
            "description": step[2],
        }

    def current_phase(self) -> str:
        """
        Return the current runbook phase.

        Rules:
          - "pre_launch"  → not all blocking pre_launch steps done
          - "launch"      → all blocking pre_launch done, not all blocking launch done
          - "post_launch" → all blocking launch done, not all blocking post_launch done
          - "completed"   → all blocking steps in all phases done
        """
        phases_in_order = ["pre_launch", "launch", "post_launch"]
        for phase in phases_in_order:
            blocking = [
                s[1] for s in STEPS if s[0] == phase and s[3]  # blocking=True
            ]
            if any(not self._is_completed(sid) for sid in blocking):
                return phase
        return "completed"

    def next_step(self) -> Optional[dict]:
        """
        Return the next uncompleted step as a dict, or None if all done.

        Dict keys: phase, step_id, description, blocking
        """
        for phase, step_id, description, blocking in STEPS:
            if not self._is_completed(step_id):
                return {
                    "phase": phase,
                    "step_id": step_id,
                    "description": description,
                    "blocking": blocking,
                }
        return None

    def progress(self) -> dict:
        """
        Return completion progress per phase and overall.

        Returns::

            {
                "pre_launch":  {"completed": 2, "total": 3},
                "launch":      {"completed": 0, "total": 4},
                "post_launch": {"completed": 0, "total": 2},
                "overall":     {"completed": 2, "total": 9},
            }

        Note: blocking_only=False — all steps (blocking + advisory) are counted.
        """
        result: dict = {}
        phases = ["pre_launch", "launch", "post_launch"]
        total_completed = 0
        total_all = 0
        for phase in phases:
            phase_steps = [s[1] for s in STEPS if s[0] == phase]
            done = sum(1 for sid in phase_steps if self._is_completed(sid))
            result[phase] = {"completed": done, "total": len(phase_steps)}
            total_completed += done
            total_all += len(phase_steps)
        result["overall"] = {"completed": total_completed, "total": total_all}
        return result

    def can_proceed_to_launch(self) -> bool:
        """
        True if all **blocking** pre_launch steps are completed.
        Advisory (non-blocking) pre_launch steps are not required.
        """
        blocking_pre = [
            s[1] for s in STEPS if s[0] == "pre_launch" and s[3]
        ]
        return all(self._is_completed(sid) for sid in blocking_pre)

    def can_proceed_to_post_launch(self) -> bool:
        """
        True if all **blocking** launch steps are completed.
        Requires can_proceed_to_launch() as well.
        """
        if not self.can_proceed_to_launch():
            return False
        blocking_launch = [
            s[1] for s in STEPS if s[0] == "launch" and s[3]
        ]
        return all(self._is_completed(sid) for sid in blocking_launch)

    def is_complete(self) -> bool:
        """True if all blocking steps in ALL phases are done."""
        for _, step_id, _, blocking in STEPS:
            if blocking and not self._is_completed(step_id):
                return False
        return True

    def completed_step_ids(self) -> List[str]:
        """Return list of step_ids that have been marked completed."""
        return list(self._state.get("completed_steps", {}).keys())

    def step_notes(self, step_id: str) -> Optional[str]:
        """Return notes for a completed step, or None if not completed."""
        entry = self._state.get("completed_steps", {}).get(step_id)
        if entry is None:
            return None
        return entry.get("notes", "")

    def to_dict(self) -> dict:
        """Return full runbook state as a dict (for JSON serialisation)."""
        return dict(self._state)

    def to_markdown(self) -> str:
        """Return a markdown progress summary."""
        prog = self.progress()
        phase = self.current_phase()
        lines = [
            "# SPA Live Launch Runbook — Progress",
            "",
            f"**Current phase:** {phase}",
            f"**Overall:** {prog['overall']['completed']}/{prog['overall']['total']} steps",
            "",
            "## Steps",
            "",
            "| Phase | Step | Description | Blocking | Status |",
            "|-------|------|-------------|----------|--------|",
        ]
        for p, sid, desc, blocking in STEPS:
            done = self._is_completed(sid)
            status = "✅ Done" if done else ("🔴 Pending" if blocking else "⚪ Optional")
            blocking_label = "Yes" if blocking else "No"
            lines.append(f"| {p} | `{sid}` | {desc} | {blocking_label} | {status} |")
        lines.append("")
        lines.append("---")
        lines.append("*spa_core/backtesting/launch_runbook.py (MP-1368 v9.84)*")
        return "\n".join(lines)


# ── CLI ────────────────────────────────────────────────────────────────────────

def _main() -> None:
    import sys

    runbook_path = "data/live/launch_runbook_state.json"
    rb = LaunchRunbook(runbook_path=runbook_path)

    if "--status" in sys.argv or len(sys.argv) == 1:
        print(rb.to_markdown())
        prog = rb.progress()
        print(f"\nCurrent phase : {rb.current_phase()}")
        print(f"Can proceed   : {rb.can_proceed_to_launch()}")
        nxt = rb.next_step()
        if nxt:
            print(f"Next step     : [{nxt['phase']}] {nxt['step_id']} — {nxt['description']}")
        else:
            print("Next step     : all done")

    elif "--complete" in sys.argv:
        idx = sys.argv.index("--complete")
        if idx + 1 >= len(sys.argv):
            print("Usage: launch_runbook.py --complete <step_id> [--notes 'text']")
            sys.exit(1)
        step_id = sys.argv[idx + 1]
        notes = ""
        if "--notes" in sys.argv:
            ni = sys.argv.index("--notes")
            if ni + 1 < len(sys.argv):
                notes = sys.argv[ni + 1]
        rb.complete_step(step_id, notes=notes)
        rb.save()
        print(f"Step {step_id!r} marked complete.")
        print(f"Current phase: {rb.current_phase()}")
        print(f"Progress: {rb.progress()['overall']}")

    else:
        print("Usage: python3 -m spa_core.backtesting.launch_runbook [--status | --complete <step_id>]")
        sys.exit(1)


if __name__ == "__main__":
    _main()
