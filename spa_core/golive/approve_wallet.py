"""
SPA Wallet Readiness Manual Approval — SPA-F003

Allows an operator to mark wallet infrastructure as ready before (or instead of)
the full go-live activation.  Creates data/wallet_ready_approved.json which is
read by spa_core/golive/checklist.py (criterion 9).

Prerequisites that the operator must complete before running this script:
  1. Gnosis Safe created and tested with a $10 test transaction
  2. Hot wallet (MetaMask) created, funded with ETH for gas
  3. Hot wallet added as Safe delegate
  4. SAFE_ADDRESS and WALLET_ADDRESS set in GitHub Secrets
  5. Private key is NOT in git history

Usage:
    python -m spa_core.golive.approve_wallet
    # or with a custom data directory:
    python -m spa_core.golive.approve_wallet --data-dir /path/to/data

The script is interactive and requires the operator to confirm:
    I CONFIRM WALLET READY
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("spa.golive.approve_wallet")

# ── Constants ─────────────────────────────────────────────────────────────────

CONFIRMATION_PHRASE = "I CONFIRM WALLET READY"
APPROVAL_FILE       = "wallet_ready_approved.json"

_DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent / "data"


# ── Core approval logic ───────────────────────────────────────────────────────

def _load_existing(data_dir: Path) -> dict | None:
    path = data_dir / APPROVAL_FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_approval(data_dir: Path, approved_by: str = "operator") -> Path:
    record = {
        "approved":     True,
        "approved_by":  approved_by,
        "approved_at":  datetime.now(timezone.utc).isoformat(),
        "note": (
            "Wallet infrastructure manually approved by operator. "
            "Gnosis Safe, hot wallet, delegate configuration, "
            "and GitHub Secrets (SAFE_ADDRESS, WALLET_ADDRESS) confirmed."
        ),
    }
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / APPROVAL_FILE
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


def run_approval(
    data_dir:      str | None = None,
    _auto_confirm: str | None = None,
) -> bool:
    """Interactive wallet-readiness approval flow.

    Args:
        data_dir:      Override the data/ directory path.
        _auto_confirm: For testing only — pass the confirmation phrase to skip
                       interactive input.

    Returns:
        True  — approval file written.
        False — operator aborted.
    """
    data_path = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR

    print("\n" + "=" * 60)
    print("  SPA WALLET READINESS APPROVAL — SPA-F003")
    print("=" * 60)

    # ── Check for existing approval ───────────────────────────────────────────
    existing = _load_existing(data_path)
    if existing and existing.get("approved"):
        print(
            f"\n✅ Wallet is already approved:\n"
            f"   Approved at:  {existing.get('approved_at')}\n"
            f"   Approved by:  {existing.get('approved_by')}\n"
        )
        if _auto_confirm is None:
            answer = input("Re-approve and overwrite? (yes/no): ").strip().lower()
            if answer != "yes":
                print("Approval aborted — existing approval preserved.")
                return False
        else:
            print("(auto-confirm: overwriting existing approval)")

    # ── Checklist ─────────────────────────────────────────────────────────────
    print(
        "\nBefore approving, confirm ALL of the following are complete:\n"
        "\n  [1] Gnosis Safe created and tested with a $10 test transaction"
        "\n  [2] Hot wallet (MetaMask) created, funded with ETH for gas, no USDC"
        "\n  [3] Hot wallet added as Safe delegate"
        "\n  [4] SAFE_ADDRESS set in GitHub Secrets"
        "\n  [5] WALLET_ADDRESS set in GitHub Secrets"
        "\n  [6] Private key is NOT in git history"
        "\n\nSee docs/v2_activation_checklist.md, Section B for full instructions.\n"
    )

    print(f'Type exactly:  {CONFIRMATION_PHRASE}')
    print()

    if _auto_confirm is not None:
        typed = _auto_confirm
        print(f"(auto-confirm input: '{typed}')")
    else:
        try:
            typed = input("Confirmation: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nApproval aborted.")
            return False

    if typed != CONFIRMATION_PHRASE:
        print(
            f"\n❌ Confirmation phrase mismatch.\n"
            f"   Expected: '{CONFIRMATION_PHRASE}'\n"
            f"   Got:      '{typed}'\n"
            "Approval aborted.\n"
        )
        return False

    # ── Write approval file ───────────────────────────────────────────────────
    try:
        path = _write_approval(data_path)
        print(f"\n✅ Wallet approval written: {path}")
    except Exception as exc:
        print(f"❌ Failed to write approval file: {exc}")
        log.error("Approval write failed: %s", exc, exc_info=True)
        return False

    print("\n" + "=" * 60)
    print("  ✅  WALLET MARKED AS READY")
    print(f"  Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)
    print(
        "\nGo-live checklist criterion 9 (Wallet Ready) will now return PASS.\n"
        "Run python -m spa_core.golive.daily_check to verify.\n"
    )
    return True


def is_wallet_approved(data_dir: str | None = None) -> bool:
    """Return True if wallet_ready_approved.json exists with approved=True."""
    data_path = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    rec = _load_existing(data_path)
    return bool(rec and rec.get("approved") is True)


def get_approval_record(data_dir: str | None = None) -> dict | None:
    """Return the approval record dict, or None if not approved."""
    data_path = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    return _load_existing(data_path)


# ── CLI entrypoint ────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SPA wallet readiness manual approval (SPA-F003)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help=f"Override data directory (default: {_DEFAULT_DATA_DIR})",
    )
    return parser.parse_args()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    args    = _parse_args()
    success = run_approval(data_dir=args.data_dir)
    sys.exit(0 if success else 1)
