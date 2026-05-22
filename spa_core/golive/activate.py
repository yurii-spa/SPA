"""
SPA Go-Live Activation Script — Phase 6 gate for real capital deployment.

Prerequisites (all must hold before this script will proceed):
  1. All 11 go-live criteria PASS (checked live against data/ files)
  2. Owner types the exact confirmation phrase interactively
  3. Activation record is written to data/activation_record.json

This script is the ONLY approved path to enabling LIVE mode on SPAWallet.
After a successful activation run, the activation record is checked by the
wallet and the monitoring pipeline before any real transaction is attempted.

Usage:
    python -m spa_core.golive.activate

CAUTION: Running this script does NOT immediately deploy capital.
It only unlocks the LIVE mode guard in SPAWallet.execute().
All individual transactions still pass through the PreExecutionSafety pipeline.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("spa.golive.activate")

# ── Constants ─────────────────────────────────────────────────────────────────
CONFIRMATION_PHRASE = "I CONFIRM LIVE TRADING"
ACTIVATION_FILE     = "activation_record.json"

# data/ is one level above spa_core/
_DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent / "data"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _setup_path() -> None:
    spa_core = str(Path(__file__).parent.parent)
    if spa_core not in sys.path:
        sys.path.insert(0, spa_core)


def _load_existing_activation(data_dir: Path) -> dict | None:
    """Return existing activation record if present, else None."""
    path = data_dir / ACTIVATION_FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_activation_record(
    data_dir:        Path,
    criteria_snapshot: list[dict],
    verdict:         str,
) -> Path:
    """Persist the activation record with timestamp and criteria snapshot."""
    record = {
        "activated_at":      datetime.now(timezone.utc).isoformat(),
        "activated_by":      "owner_interactive",
        "confirmation_phrase": CONFIRMATION_PHRASE,
        "verdict_at_activation": verdict,
        "criteria_snapshot": criteria_snapshot,
        "criteria_passed":   sum(1 for c in criteria_snapshot if c["status"] == "PASS"),
        "criteria_total":    len(criteria_snapshot),
        "warning":           (
            "LIVE trading is now unlocked. All transactions still pass through "
            "PreExecutionSafety. To re-lock, delete this file."
        ),
    }
    path = data_dir / ACTIVATION_FILE
    path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    return path


# ── Core activation logic ─────────────────────────────────────────────────────

def check_all_criteria_pass(data_dir: str | None = None) -> tuple[bool, dict]:
    """
    Run the full go-live checklist and return (all_pass, check_result).

    'all_pass' is True only when every criterion (including Wallet Ready) has
    status PASS — no WARN, no PENDING, no FAIL is tolerated for live activation.

    Returns:
        (True, check_result)  if all 11 criteria PASS
        (False, check_result) otherwise
    """
    _setup_path()
    from golive.checklist import run_full_check

    data_path = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    result    = run_full_check(str(data_path))
    criteria  = result.get("criteria", [])
    all_pass  = all(c["status"] == "PASS" for c in criteria)
    return all_pass, result


def run_activation(data_dir: str | None = None, _auto_confirm: str | None = None) -> bool:
    """
    Interactive activation flow.

    Args:
        data_dir:      Override the data/ directory path.
        _auto_confirm: For testing only — pass the confirmation phrase to skip
                       interactive input.  Production usage must leave this None.

    Returns:
        True  — activation successful, activation_record.json written.
        False — activation aborted or criteria not met.
    """
    _setup_path()
    data_path = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    data_path.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 60)
    print("  SPA GO-LIVE ACTIVATION — Phase 6")
    print("=" * 60)

    # ── Check for an existing activation record ───────────────────────────────
    existing = _load_existing_activation(data_path)
    if existing:
        print(
            f"\n⚠️  An existing activation record was found:\n"
            f"   Activated at: {existing.get('activated_at')}\n"
            f"   Verdict at activation: {existing.get('verdict_at_activation')}\n"
        )
        if _auto_confirm is None:
            answer = input("Re-activate and overwrite? (yes/no): ").strip().lower()
            if answer != "yes":
                print("Activation aborted — existing record preserved.")
                return False
        else:
            print("(auto-confirm: overwriting existing record)")

    # ── Step 1: Run all 11 criteria ──────────────────────────────────────────
    print("\n[1/3] Checking all 11 go-live criteria…\n")

    try:
        all_pass, check_result = check_all_criteria_pass(str(data_path))
    except Exception as exc:
        print(f"❌ Failed to run checklist: {exc}")
        log.error("Checklist failed during activation: %s", exc, exc_info=True)
        return False

    criteria = check_result.get("criteria", [])
    verdict  = check_result.get("verdict", "NOT_READY")

    # Print each criterion
    icon_map = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️ ", "PENDING": "⏳"}
    for c in criteria:
        icon = icon_map.get(c["status"], "?")
        print(f"  {icon}  [{c['status']:<7}]  {c['name']}")
        if c["status"] != "PASS":
            print(f"           ↳ {c.get('note', '')}")

    passed  = sum(1 for c in criteria if c["status"] == "PASS")
    total   = len(criteria)
    print(f"\nResult: {passed}/{total} criteria PASS — Verdict: {verdict}\n")

    if not all_pass:
        failing = [
            f"  • {c['name']} [{c['status']}]: {c.get('note', '')}"
            for c in criteria if c["status"] != "PASS"
        ]
        print("❌ Activation BLOCKED — requires all criteria PASS:\n")
        print("\n".join(failing))
        print(
            "\nResolve the above issues and re-run this script.\n"
            "Wallet remains locked in LIVE mode.\n"
        )
        return False

    print("✅ All criteria PASS.")

    # ── Step 2: Owner confirmation ────────────────────────────────────────────
    print("\n[2/3] Owner confirmation required.")
    print(
        "\n⚠️  WARNING: After activation, SPAWallet.execute() will be able to\n"
        "    submit REAL on-chainsactions that move REAL capital.\n"
        "    Every transaction still passes through PreExecutionSafety,\n"
        "    but the NotImplementedError hard-block will be removed.\n"
    )
    print(f'    Type exactly:  {CONFIRMATION_PHRASE}')
    print()

    if _auto_confirm is not None:
        typed = _auto_confirm
        print(f"(auto-confirm input: '{typed}')")
    else:
        try:
            typed = input("Confirmation: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nActivation aborted.")
            return False

    if typed != CONFIRMATION_PHRASE:
        print(
            f"\n❌ Confirmation phrase mismatch.\n"
            f"   Expected: '{CONFIRMATION_PHRASE}'\n"
            f"   Got:      '{typed}'\n"
            "Activation aborted.\n"
        )
        return False

    # ── Step 3: Write sentinel + activation record ────────────────────────────
    print("\n[3/3] Writing wallet sentinel and activation record…")
    try:
        # Write wallet_ready.sentinel so check_wallet_ready() returns PASS
        sentinel_path = data_path / "wallet_ready.sentinel"
        sentinel_path.write_text(
            datetime.now(timezone.utc).isoformat(),
            encoding="utf-8",
        )
        print(f"✅ Wallet sentinel written: {sentinel_path}")

        record_path = _write_activation_record(
            data_dir=data_path,
            criteria_snapshot=criteria,
            verdict=verdict,
        )
        print(f"\n✅ Activation record written: {record_path}\n")
    except Exception as exc:
        print(f"❌ Failed to write activation record: {exc}")
        log.error("Activation record write failed: %s", exc, exc_info=True)
        return False

    print("=" * 60)
    print("  ✅  LIVE MODE ACTIVATED")
    print(f"  Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)
    print()
    print("SPAWallet in LIVE mode will now execute real transactions.")
    print("Monitor closely. Kill switch: PreExecutionSafety.activate_kill_switch()")
    print()

    return True


# ── Public helper for wallet / pipeline checks ────────────────────────────────

def is_activated(data_dir: str | None = None) -> bool:
    """
    Return True if a valid activation record exists in data/.

    Used by monitoring scripts to verify the system has been deliberately
    activated before allowing LIVE transactions.
    """
    data_path = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    record = _load_existing_activation(data_path)
    return record is not None and record.get("activated_at") is not None


def get_activation_record(data_dir: str | None = None) -> dict | None:
    """Return the activation record dict, or None if not activated."""
    data_path = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    return _load_existing_activation(data_path)


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    success = run_activation()
    sys.exit(0 if success else 1)
