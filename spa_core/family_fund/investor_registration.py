"""
spa_core/family_fund/investor_registration.py

Investor registration and KYC workflow for Family Fund.

Flow:
  1. Investor submits registration request
  2. System creates pending record
  3. Yurii manually reviews and approves/rejects
  4. On approval: investor gets access token

PRODUCT_DECISIONS:
  - Manual KYC (no automated verification)
  - Minimum investment: $10,000
  - Lock-up: 90 days
  - Assets: USDT + USDC accepted
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from spa_core.utils.atomic import atomic_save

__all__ = [
    "InvestorRecord",
    "InvestorRegistry",
    "INVESTOR_STATUSES",
    "MIN_INVESTMENT_USD",
    "LOCK_UP_DAYS",
]

INVESTOR_STATUSES = ["PENDING", "APPROVED", "REJECTED", "SUSPENDED"]
MIN_INVESTMENT_USD = 10_000.0
LOCK_UP_DAYS = 90

_DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "family_fund" / "investor_registry.json"
)


@dataclass
class InvestorRecord:
    """Single investor registration record."""

    investor_id: str
    name: str
    email: str
    requested_amount_usd: float
    status: str = "PENDING"
    created_at: str = ""
    approved_at: Optional[str] = None
    rejected_reason: Optional[str] = None
    kyc_notes: str = ""
    suspended_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "investor_id": self.investor_id,
            "name": self.name,
            "email": self.email,
            "requested_amount_usd": self.requested_amount_usd,
            "status": self.status,
            "created_at": self.created_at,
            "approved_at": self.approved_at,
            "rejected_reason": self.rejected_reason,
            "kyc_notes": self.kyc_notes,
            "suspended_reason": self.suspended_reason,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "InvestorRecord":
        return cls(
            investor_id=str(d["investor_id"]),
            name=str(d["name"]),
            email=str(d["email"]),
            requested_amount_usd=float(d["requested_amount_usd"]),
            status=str(d.get("status", "PENDING")),
            created_at=str(d.get("created_at", "")),
            approved_at=d.get("approved_at"),
            rejected_reason=d.get("rejected_reason"),
            kyc_notes=str(d.get("kyc_notes", "")),
            suspended_reason=d.get("suspended_reason"),
        )


class InvestorRegistry:
    """
    Persistent registry of investor registration records.

    Storage: JSON file at registry_path.
    All writes are atomic (mkstemp + os.replace).
    """

    def __init__(
        self,
        registry_path: str = str(_DEFAULT_REGISTRY_PATH),
    ) -> None:
        self.registry_path = str(registry_path)
        self._records: dict[str, InvestorRecord] = {}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load records from JSON. Creates empty store if file is missing."""
        p = Path(self.registry_path)
        if not p.exists():
            self._records = {}
            return
        with open(p, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        self._records = {}
        for rid, rdata in raw.get("records", {}).items():
            self._records[rid] = InvestorRecord.from_dict(rdata)

    def save(self) -> None:
        """Atomically write current records to JSON via atomic_save."""
        p = Path(self.registry_path)
        payload = {"records": {rid: rec.to_dict() for rid, rec in self._records.items()}}
        atomic_save(payload, str(p))

    # ------------------------------------------------------------------
    # Registration workflow
    # ------------------------------------------------------------------

    def register(self, name: str, email: str, amount_usd: float) -> InvestorRecord:
        """
        Creates a PENDING registration record.

        Raises:
            ValueError: if amount_usd < MIN_INVESTMENT_USD.
            ValueError: if email is already registered.
        """
        if amount_usd < MIN_INVESTMENT_USD:
            raise ValueError(
                f"Minimum investment is ${MIN_INVESTMENT_USD:,.0f} USD; "
                f"received ${amount_usd:,.2f}"
            )

        norm_email = email.strip().lower()
        for rec in self._records.values():
            if rec.email.strip().lower() == norm_email:
                raise ValueError(f"Email already registered: {email!r}")

        investor_id = self._generate_id(email)
        now = _utcnow_iso()

        record = InvestorRecord(
            investor_id=investor_id,
            name=name,
            email=email.strip(),
            requested_amount_usd=float(amount_usd),
            status="PENDING",
            created_at=now,
        )
        self._records[investor_id] = record
        return record

    def approve(self, investor_id: str, kyc_notes: str = "") -> InvestorRecord:
        """Move a PENDING record to APPROVED."""
        rec = self._get_or_raise(investor_id)
        if rec.status != "PENDING":
            raise ValueError(
                f"approve() requires PENDING status; investor {investor_id!r} is {rec.status!r}"
            )
        rec.status = "APPROVED"
        rec.approved_at = _utcnow_iso()
        rec.kyc_notes = kyc_notes
        return rec

    def reject(self, investor_id: str, reason: str) -> InvestorRecord:
        """Move a PENDING record to REJECTED."""
        rec = self._get_or_raise(investor_id)
        if rec.status != "PENDING":
            raise ValueError(
                f"reject() requires PENDING status; investor {investor_id!r} is {rec.status!r}"
            )
        rec.status = "REJECTED"
        rec.rejected_reason = reason
        return rec

    def suspend(self, investor_id: str, reason: str) -> InvestorRecord:
        """Move an APPROVED record to SUSPENDED."""
        rec = self._get_or_raise(investor_id)
        if rec.status != "APPROVED":
            raise ValueError(
                f"suspend() requires APPROVED status; investor {investor_id!r} is {rec.status!r}"
            )
        rec.status = "SUSPENDED"
        rec.suspended_reason = reason
        return rec

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, investor_id: str) -> Optional[InvestorRecord]:
        """Return record by investor_id, or None."""
        return self._records.get(investor_id)

    def list_by_status(self, status: str) -> list:
        """Return all records matching the given status."""
        return [r for r in self._records.values() if r.status == status]

    def total_committed_usd(self) -> float:
        """Sum of requested_amount_usd for APPROVED investors only."""
        return sum(
            r.requested_amount_usd
            for r in self._records.values()
            if r.status == "APPROVED"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_or_raise(self, investor_id: str) -> InvestorRecord:
        rec = self._records.get(investor_id)
        if rec is None:
            raise KeyError(f"Investor not found: {investor_id!r}")
        return rec

    def _generate_id(self, email: str) -> str:
        """Generate a unique 16-char hex investor_id."""
        raw = f"{email.strip().lower()}:{time.monotonic_ns()}"
        candidate = hashlib.sha256(raw.encode()).hexdigest()[:16]
        # Guarantee uniqueness within current session
        while candidate in self._records:
            raw = f"{raw}:{time.monotonic_ns()}"
            candidate = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return candidate


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _utcnow_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
