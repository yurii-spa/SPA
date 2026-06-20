"""
spa_core/family_fund/lead_tracker.py

Contact form lead tracker.
Stores leads and sends Telegram notification to Yurii.

Lead flow: NEW → CONTACTED → QUALIFIED → INVESTOR (or REJECTED)

SECRETS POLICY: No tokens/keys ever written to this file.
Credentials are fetched from macOS Keychain via subprocess.
Pure stdlib. No external dependencies.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from spa_core.base import BaseAnalytics
from spa_core.utils.atomic import atomic_save
from spa_core.utils.errors import ConfigError

__all__ = ["Lead", "LeadTracker", "LEAD_STATUSES"]

LEAD_STATUSES = ["NEW", "CONTACTED", "QUALIFIED", "INVESTOR", "REJECTED"]

_PIPELINE_STATUSES = {"NEW", "QUALIFIED"}  # counted in total_pipeline_usd

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


@dataclass
class Lead:
    """A prospective investor in the SPA Family Fund."""

    lead_id: str
    name: str
    email: str
    telegram_handle: Optional[str]
    interested_amount_usd: float
    message: str
    status: str = "NEW"
    created_at: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if self.status not in LEAD_STATUSES:
            raise ValueError(
                f"Invalid status {self.status!r}. Must be one of {LEAD_STATUSES}"
            )


class LeadTracker(BaseAnalytics):
    """
    Tracks prospective investors through a simple CRM pipeline.

    Storage: JSON file at ``leads_path`` (atomic writes via tmp+replace).
    Notifications: Telegram bot (credentials from macOS Keychain).

    Usage::

        tracker = LeadTracker()
        tracker.load()
        lead = tracker.add_lead(
            name="Ivan Petrov",
            email="ivan@example.com",
            amount_usd=50_000,
            message="Interested in Core strategy",
        )
        print(tracker.summary())
    """

    OUTPUT_PATH = "data/family_fund/leads.json"

    def __init__(
        self,
        leads_path: str = "data/family_fund/leads.json",
        *,
        telegram_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
        base_dir: str = ".",
    ) -> None:
        super().__init__(base_dir)
        self.leads_path = leads_path
        self._telegram_token_override = telegram_token
        self._telegram_chat_id_override = telegram_chat_id
        self._leads: Dict[str, Lead] = {}  # keyed by lead_id

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    def load(self) -> None:
        """Load leads from disk. Safe to call even if file does not exist."""
        if not os.path.exists(self.leads_path):
            self._leads = {}
            return
        with open(self.leads_path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        self._leads = {}
        for item in raw.get("leads", []):
            lead = Lead(**item)
            self._leads[lead.lead_id] = lead

    def save(self) -> None:
        """Atomic save via atomic_save."""
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "leads": [asdict(lead) for lead in self._leads.values()],
        }
        atomic_save(payload, self.leads_path)

    # ------------------------------------------------------------------ #
    # Lead management
    # ------------------------------------------------------------------ #

    def add_lead(
        self,
        name: str,
        email: str,
        amount_usd: float,
        message: str = "",
        telegram_handle: Optional[str] = None,
    ) -> Lead:
        """
        Create a NEW lead and persist it.

        Deduplication: if a lead with the same ``email`` already exists,
        returns the existing lead without creating a duplicate and without
        sending a Telegram notification.

        Sends a Telegram notification to Yurii on successful creation.
        """
        email = email.strip().lower()
        # De-duplicate by email
        existing = self._find_by_email(email)
        if existing is not None:
            return existing

        lead_id = str(uuid.uuid4())
        lead = Lead(
            lead_id=lead_id,
            name=name.strip(),
            email=email,
            telegram_handle=telegram_handle,
            interested_amount_usd=float(amount_usd),
            message=message,
            status="NEW",
        )
        self._leads[lead_id] = lead
        self.save()
        self.send_telegram_notification(lead)
        return lead

    def update_status(self, lead_id: str, status: str, notes: str = "") -> Lead:
        """
        Move a lead through the pipeline.

        :param lead_id: UUID of the lead.
        :param status: One of LEAD_STATUSES.
        :param notes: Optional internal notes appended to the lead.
        :raises KeyError: If lead_id is not found.
        :raises ValueError: If status is invalid.
        """
        if status not in LEAD_STATUSES:
            raise ValueError(
                f"Invalid status {status!r}. Must be one of {LEAD_STATUSES}"
            )
        if lead_id not in self._leads:
            raise KeyError(f"Lead not found: {lead_id!r}")
        lead = self._leads[lead_id]
        lead.status = status
        if notes:
            lead.notes = (
                f"{lead.notes}\n{notes}".strip() if lead.notes else notes
            )
        self.save()
        return lead

    def list_by_status(self, status: str) -> List[Lead]:
        """Return all leads with the given status, sorted by created_at."""
        if status not in LEAD_STATUSES:
            raise ValueError(
                f"Invalid status {status!r}. Must be one of {LEAD_STATUSES}"
            )
        return sorted(
            [lead for lead in self._leads.values() if lead.status == status],
            key=lambda l: l.created_at,
        )

    def get_lead(self, lead_id: str) -> Lead:
        """Retrieve a single lead by ID. Raises KeyError if not found."""
        if lead_id not in self._leads:
            raise KeyError(f"Lead not found: {lead_id!r}")
        return self._leads[lead_id]

    def all_leads(self) -> List[Lead]:
        """Return all leads sorted by created_at (oldest first)."""
        return sorted(self._leads.values(), key=lambda l: l.created_at)

    # ------------------------------------------------------------------ #
    # Analytics
    # ------------------------------------------------------------------ #

    def total_pipeline_usd(self) -> float:
        """Sum of interested_amount_usd for NEW + QUALIFIED leads."""
        return sum(
            lead.interested_amount_usd
            for lead in self._leads.values()
            if lead.status in _PIPELINE_STATUSES
        )

    def summary(self) -> dict:
        """
        Return a summary dict with:
        - counts: {status: count} for all LEAD_STATUSES
        - total_leads: total number of leads
        - pipeline_usd: total_pipeline_usd()
        """
        counts = {status: 0 for status in LEAD_STATUSES}
        for lead in self._leads.values():
            counts[lead.status] = counts.get(lead.status, 0) + 1
        return {
            "counts": counts,
            "total_leads": len(self._leads),
            "pipeline_usd": self.total_pipeline_usd(),
        }

    def to_dict(self) -> dict:
        """Returns lead tracker summary as JSON-serializable dict (BaseAnalytics)."""
        return self.summary()

    # ------------------------------------------------------------------ #
    # Telegram
    # ------------------------------------------------------------------ #

    def send_telegram_notification(self, lead: Lead) -> bool:
        """
        Send a Telegram notification to Yurii about a new lead.
        Credentials are fetched from macOS Keychain.
        Returns True on success, False on any error (never raises).
        """
        try:
            token, chat_id = self._resolve_telegram_credentials()
            text = self._format_lead_message(lead)
            self._post_telegram(token, chat_id, text)
            return True
        except Exception:
            return False

    def _format_lead_message(self, lead: Lead) -> str:
        amount_str = f"${lead.interested_amount_usd:,.0f}"
        tg = lead.telegram_handle or "—"
        msg_preview = (lead.message[:120] + "…") if len(lead.message) > 120 else lead.message
        return (
            f"🔔 *Новый лид — SPA Family Fund*\n\n"
            f"👤 Имя: `{lead.name}`\n"
            f"📧 Email: `{lead.email}`\n"
            f"💬 Telegram: `{tg}`\n"
            f"💰 Сумма: `{amount_str}`\n"
            f"📝 Сообщение: {msg_preview}\n\n"
            f"🆔 ID: `{lead.lead_id}`\n"
            f"🕐 Создан: `{lead.created_at}`"
        )

    def _resolve_telegram_credentials(self):
        """Return (token, chat_id) from overrides or macOS Keychain."""
        token = (
            self._telegram_token_override
            if self._telegram_token_override is not None
            else self._keychain_get("TELEGRAM_BOT_TOKEN_SPA")
        )
        chat_id = (
            self._telegram_chat_id_override
            if self._telegram_chat_id_override is not None
            else self._keychain_get("TELEGRAM_CHAT_ID_SPA")
        )
        return token, chat_id

    @staticmethod
    def _keychain_get(key: str) -> str:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", key, "-w"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise ConfigError(
                key,
                f"Keychain lookup failed: {result.stderr.strip()}",
            )
        return result.stdout.strip()

    @staticmethod
    def _post_telegram(token: str, chat_id: str, text: str) -> None:
        url = _TELEGRAM_API.format(token=token)
        payload = json.dumps({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _find_by_email(self, email: str) -> Optional[Lead]:
        """Return the first lead matching email (case-insensitive), or None."""
        email = email.strip().lower()
        for lead in self._leads.values():
            if lead.email.lower() == email:
                return lead
        return None
