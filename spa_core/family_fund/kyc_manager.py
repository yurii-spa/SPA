"""
spa_core/family_fund/kyc_manager.py — MP-1480 Family Fund KYC Workflow

Manages KYC records for Family Fund investors.
Stdlib only. Atomic writes. LLM FORBIDDEN.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Dict, List, Optional

from spa_core.utils.atomic import atomic_save

__all__ = ["KYCStatus", "KYCRecord", "KYCManager", "KYC_EXPIRY_DAYS"]

KYC_EXPIRY_DAYS = 365


class KYCStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass
class KYCRecord:
    investor_id: str
    status: KYCStatus = KYCStatus.PENDING
    documents: List[str] = field(default_factory=list)
    submitted_at: Optional[str] = None
    approved_at: Optional[str] = None
    rejected_at: Optional[str] = None
    expires_at: Optional[str] = None
    rejection_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "investor_id": self.investor_id,
            "status": self.status.value,
            "documents": list(self.documents),
            "submitted_at": self.submitted_at,
            "approved_at": self.approved_at,
            "rejected_at": self.rejected_at,
            "expires_at": self.expires_at,
            "rejection_reason": self.rejection_reason,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "KYCRecord":
        return cls(
            investor_id=d["investor_id"],
            status=KYCStatus(d.get("status", KYCStatus.PENDING.value)),
            documents=d.get("documents", []),
            submitted_at=d.get("submitted_at", None),
            approved_at=d.get("approved_at", None),
            rejected_at=d.get("rejected_at", None),
            expires_at=d.get("expires_at", None),
            rejection_reason=d.get("rejection_reason", None),
        )


def _now_utc() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(s: str) -> datetime:
    """Parse an ISO 8601 UTC datetime string."""
    return datetime.fromisoformat(s)


class KYCManager:
    """
    Manages KYC records for Family Fund investors.

    Records are persisted atomically to a JSON file:
      {"records": [...], "updated_at": "<iso>"}

    All timestamps are UTC ISO-8601 strings.
    LLM FORBIDDEN — no AI/LLM calls permitted here.
    """

    DEFAULT_DATA_FILE = "data/kyc_records.json"

    def __init__(self, data_file: Optional[str] = None, base_dir: str = ".") -> None:
        if data_file is not None:
            # Accept absolute or relative; if relative, join with base_dir
            if os.path.isabs(data_file):
                self._path = data_file
            else:
                self._path = os.path.join(base_dir, data_file)
        else:
            self._path = os.path.join(base_dir, self.DEFAULT_DATA_FILE)

        self._records: Dict[str, KYCRecord] = {}
        self._load()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def submit(self, investor_id: str, documents: List[str]) -> KYCRecord:
        """
        Create (or overwrite) a PENDING KYC record for investor_id.
        Sets submitted_at to now; clears approval/rejection fields.
        """
        record = KYCRecord(
            investor_id=investor_id,
            status=KYCStatus.PENDING,
            documents=list(documents),
            submitted_at=_now_utc(),
            approved_at=None,
            rejected_at=None,
            expires_at=None,
            rejection_reason=None,
        )
        self._records[investor_id] = record
        self._save()
        return record

    def approve(self, investor_id: str) -> KYCRecord:
        """
        Approve a KYC record.
        Raises KeyError if no record exists for investor_id.
        Sets status=APPROVED, approved_at=now, expires_at=now+365d.
        """
        if investor_id not in self._records:
            raise KeyError(f"No KYC record for investor_id={investor_id!r}")
        record = self._records[investor_id]
        now = datetime.now(timezone.utc)
        record.status = KYCStatus.APPROVED
        record.approved_at = now.isoformat()
        record.expires_at = (now + timedelta(days=KYC_EXPIRY_DAYS)).isoformat()
        record.rejected_at = None
        record.rejection_reason = None
        self._save()
        return record

    def reject(self, investor_id: str, reason: str = "") -> KYCRecord:
        """
        Reject a KYC record.
        Raises KeyError if no record exists for investor_id.
        Sets status=REJECTED and stores reason.
        """
        if investor_id not in self._records:
            raise KeyError(f"No KYC record for investor_id={investor_id!r}")
        record = self._records[investor_id]
        record.status = KYCStatus.REJECTED
        record.rejected_at = _now_utc()
        record.rejection_reason = reason
        record.approved_at = None
        record.expires_at = None
        self._save()
        return record

    def is_cleared(self, investor_id: str) -> bool:
        """
        Return True only if the investor has an APPROVED record that has
        not yet expired. Automatically triggers expiry check first.
        """
        self._refresh_expiry(investor_id)
        record = self._records.get(investor_id)
        if record is None:
            return False
        return record.status == KYCStatus.APPROVED

    def get_record(self, investor_id: str) -> Optional[KYCRecord]:
        """Return the KYCRecord for investor_id, or None if not found."""
        return self._records.get(investor_id)

    def list_records(self) -> List[KYCRecord]:
        """Return all KYC records."""
        return list(self._records.values())

    def list_by_status(self, status: KYCStatus) -> List[KYCRecord]:
        """Return all records with the given status."""
        return [r for r in self._records.values() if r.status == status]

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _refresh_expiry(self, investor_id: str) -> None:
        """
        If the record for investor_id is APPROVED but expires_at is in the
        past, set its status to EXPIRED and persist.
        """
        record = self._records.get(investor_id)
        if record is None:
            return
        if record.status != KYCStatus.APPROVED:
            return
        if record.expires_at is None:
            return
        expires_dt = _parse_dt(record.expires_at)
        now = datetime.now(timezone.utc)
        if now >= expires_dt:
            record.status = KYCStatus.EXPIRED
            self._save()

    def _load(self) -> None:
        """Load records from the JSON file if it exists."""
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            for raw in data.get("records", []):
                rec = KYCRecord.from_dict(raw)
                self._records[rec.investor_id] = rec
        except (json.JSONDecodeError, KeyError, ValueError):
            # Corrupt file — start fresh rather than crash
            self._records = {}

    def _save(self) -> None:
        """Atomically persist all records to the JSON file."""
        data = {
            "records": [r.to_dict() for r in self._records.values()],
            "updated_at": _now_utc(),
        }
        atomic_save(data, self._path)
