"""
spa_core/family_fund/withdrawal_engine.py

Manages investor withdrawal requests and processing.

States: REQUESTED → PENDING_REVIEW → APPROVED → PROCESSING → COMPLETED | REJECTED

Rules:
  - Minimum withdrawal: $1,000 USD
  - Processing time: T+5 business days
  - All writes are atomic (mkstemp + os.replace)
  - Pure stdlib — no external dependencies
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional

__all__ = [
    "WithdrawalStatus",
    "WithdrawalRequest",
    "WithdrawalEngine",
]


# ---------------------------------------------------------------------------
# Enums / Dataclasses
# ---------------------------------------------------------------------------

class WithdrawalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


@dataclass
class WithdrawalRequest:
    """A single investor withdrawal request."""

    request_id: str
    investor_id: str
    amount_usd: float
    status: WithdrawalStatus = WithdrawalStatus.REQUESTED
    requested_at: str = ""
    completed_at: Optional[str] = None
    rejection_reason: Optional[str] = None
    processing_notes: str = ""

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "investor_id": self.investor_id,
            "amount_usd": self.amount_usd,
            "status": self.status.value,
            "requested_at": self.requested_at,
            "completed_at": self.completed_at,
            "rejection_reason": self.rejection_reason,
            "processing_notes": self.processing_notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WithdrawalRequest":
        return cls(
            request_id=str(d["request_id"]),
            investor_id=str(d["investor_id"]),
            amount_usd=float(d["amount_usd"]),
            status=WithdrawalStatus(d.get("status", "REQUESTED")),
            requested_at=str(d.get("requested_at", "")),
            completed_at=d.get("completed_at"),
            rejection_reason=d.get("rejection_reason"),
            processing_notes=str(d.get("processing_notes", "")),
        )


# ---------------------------------------------------------------------------
# WithdrawalEngine
# ---------------------------------------------------------------------------

class WithdrawalEngine:
    """
    Manages the full lifecycle of investor withdrawal requests.

    Storage: <base_dir>/withdrawals.json (atomically written).
    """

    MIN_WITHDRAWAL: float = 1_000.0   # $1 K minimum
    PROCESSING_DAYS: int = 5          # T+5 business days

    # Internal status sets used for guard logic
    _TERMINAL = frozenset({WithdrawalStatus.COMPLETED, WithdrawalStatus.REJECTED})
    _APPROVABLE = frozenset({WithdrawalStatus.REQUESTED, WithdrawalStatus.PENDING_REVIEW})
    _PENDING = frozenset({WithdrawalStatus.REQUESTED, WithdrawalStatus.PENDING_REVIEW})

    def __init__(self, base_dir: str = ".") -> None:
        self._base_dir = str(base_dir)
        os.makedirs(self._base_dir, exist_ok=True)
        self._save_path = os.path.join(self._base_dir, "withdrawals.json")
        self._requests: dict[str, WithdrawalRequest] = {}

    # ------------------------------------------------------------------
    # Public API — state transitions
    # ------------------------------------------------------------------

    def request_withdrawal(self, investor_id: str, amount_usd: float) -> WithdrawalRequest:
        """
        Create a withdrawal request in REQUESTED state.

        Raises:
            ValueError: if amount_usd < MIN_WITHDRAWAL.
        """
        if amount_usd < self.MIN_WITHDRAWAL:
            raise ValueError(
                f"Minimum withdrawal is ${self.MIN_WITHDRAWAL:,.0f} USD; "
                f"received ${amount_usd:,.2f}"
            )
        request_id = self._generate_id(investor_id)
        req = WithdrawalRequest(
            request_id=request_id,
            investor_id=investor_id,
            amount_usd=float(amount_usd),
            status=WithdrawalStatus.REQUESTED,
            requested_at=_utcnow_iso(),
        )
        self._requests[request_id] = req
        return req

    def approve(self, request_id: str, notes: str = "") -> WithdrawalRequest:
        """
        Move REQUESTED or PENDING_REVIEW → APPROVED.

        Raises:
            KeyError: if request_id not found.
            ValueError: if status is not in {REQUESTED, PENDING_REVIEW}.
        """
        req = self._get_or_raise(request_id)
        if req.status not in self._APPROVABLE:
            raise ValueError(
                f"Cannot approve withdrawal in state {req.status.value!r}; "
                f"must be REQUESTED or PENDING_REVIEW"
            )
        req.status = WithdrawalStatus.APPROVED
        req.processing_notes = notes
        return req

    def reject(self, request_id: str, reason: str) -> WithdrawalRequest:
        """
        Reject a withdrawal request with an explanatory reason.

        Raises:
            KeyError: if request_id not found.
            ValueError: if request is already in a terminal state.
        """
        req = self._get_or_raise(request_id)
        if req.status in self._TERMINAL:
            raise ValueError(
                f"Cannot reject withdrawal in terminal state {req.status.value!r}"
            )
        req.status = WithdrawalStatus.REJECTED
        req.rejection_reason = reason
        return req

    def complete(self, request_id: str) -> WithdrawalRequest:
        """
        Mark an APPROVED withdrawal as COMPLETED with a UTC timestamp.

        Raises:
            KeyError: if request_id not found.
            ValueError: if already COMPLETED.
            ValueError: if status is not APPROVED.
        """
        req = self._get_or_raise(request_id)
        if req.status == WithdrawalStatus.COMPLETED:
            raise ValueError(
                f"Withdrawal {request_id!r} is already COMPLETED"
            )
        if req.status != WithdrawalStatus.APPROVED:
            raise ValueError(
                f"Cannot complete withdrawal in state {req.status.value!r}; "
                f"expected APPROVED"
            )
        req.status = WithdrawalStatus.COMPLETED
        req.completed_at = _utcnow_iso()
        return req

    # ------------------------------------------------------------------
    # Public API — queries
    # ------------------------------------------------------------------

    def get_pending(self) -> List[WithdrawalRequest]:
        """Return all requests in REQUESTED or PENDING_REVIEW state."""
        return [r for r in self._requests.values() if r.status in self._PENDING]

    def investor_total_withdrawn(self, investor_id: str) -> float:
        """Return sum of amount_usd for all COMPLETED withdrawals by investor."""
        return sum(
            r.amount_usd
            for r in self._requests.values()
            if r.investor_id == investor_id and r.status == WithdrawalStatus.COMPLETED
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Atomically persist all requests to <base_dir>/withdrawals.json."""
        p = Path(self._save_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "withdrawals": {
                rid: req.to_dict() for rid, req in self._requests.items()
            }
        }
        fd, tmp_path = tempfile.mkstemp(dir=str(p.parent), prefix=".withdrawals_tmp_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            os.replace(tmp_path, str(p))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def load(self) -> None:
        """Load requests from disk. No-op (empty store) if file does not exist."""
        p = Path(self._save_path)
        if not p.exists():
            self._requests = {}
            return
        with open(p, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        self._requests = {
            rid: WithdrawalRequest.from_dict(rdata)
            for rid, rdata in raw.get("withdrawals", {}).items()
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_or_raise(self, request_id: str) -> WithdrawalRequest:
        req = self._requests.get(request_id)
        if req is None:
            raise KeyError(f"Withdrawal request not found: {request_id!r}")
        return req

    def _generate_id(self, investor_id: str) -> str:
        """Generate a unique 16-char hex request_id."""
        raw = f"{investor_id}:{time.monotonic_ns()}"
        candidate = hashlib.sha256(raw.encode()).hexdigest()[:16]
        while candidate in self._requests:
            raw = f"{raw}:{time.monotonic_ns()}"
            candidate = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return candidate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow_iso() -> str:
    """Return current UTC time as ISO 8601 string (UTC, second precision)."""
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
