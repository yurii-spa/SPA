"""spa_core/cmo/draft_store.py — CMO draft store (flow B: draft → owner-approve → publish).

Drafts are JSON files in data/cmo_drafts/ keyed by draft ID (cmo_YYYYMMDD_NNN).
Each draft has a status field: "draft" | "approved" | "rejected" | "published".

All writes are atomic (same-dir tmp + os.replace). stdlib-only, no LLM, fail-CLOSED.

Usage::
    from spa_core.cmo.draft_store import DraftStore
    store = DraftStore()
    draft_id = store.save_draft(source_facts, draft_text, gate_result, rewrite_method, date_str)
    drafts = store.list_drafts(status="draft")
    store.approve(draft_id)
    store.reject(draft_id)
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

from spa_core.cmo.honesty_gate import GateResult

_ROOT = Path(__file__).resolve().parent.parent.parent  # repo root
DRAFTS_DIR = _ROOT / "data" / "cmo_drafts"

_VALID_STATUSES = {"draft", "approved", "rejected", "published"}


@dataclass
class Draft:
    id: str
    date: str                # ISO date of the source entry
    created_at: str          # ISO-8601 timestamp
    status: str              # draft | approved | rejected | published
    source_facts: dict       # facts used to generate the draft
    draft_text: str          # the template/LLM-produced text
    fallback_text: str       # always-passing dry version
    gate_passed: bool
    gate_violations: list[str]
    rewrite_method: str      # "template_v1" or "llm_claude" etc.
    approved_at: str | None = None
    rejected_at: str | None = None
    published_at: str | None = None
    published_to: str | None = None  # slug / URL once published


class DraftStore:
    def __init__(self, drafts_dir: Path | None = None) -> None:
        self._dir = Path(drafts_dir) if drafts_dir else DRAFTS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    # ── internal I/O ──────────────────────────────────────────────────────────

    def _path(self, draft_id: str) -> Path:
        return self._dir / f"{draft_id}.json"

    def _write(self, draft: Draft) -> None:
        """Atomic write: tmp file in same dir then os.replace."""
        p = self._path(draft.id)
        tmp = p.with_suffix(".tmp")
        data = asdict(draft)
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        os.replace(tmp, p)

    def _read(self, draft_id: str) -> Draft | None:
        p = self._path(draft_id)
        try:
            data = json.loads(p.read_text())
            return Draft(**data)
        except (OSError, ValueError, TypeError):
            return None

    # ── public API ────────────────────────────────────────────────────────────

    def save_draft(
        self,
        source_facts: dict[str, Any],
        draft_text: str,
        fallback_text: str,
        gate_result: GateResult,
        rewrite_method: str,
        date_str: str,
    ) -> str:
        """Persist a new draft. Returns the draft_id."""
        existing_ids = {p.stem for p in self._dir.glob("cmo_*.json")}
        date_key = date_str.replace("-", "")
        n = sum(1 for iid in existing_ids if iid.startswith(f"cmo_{date_key}"))
        draft_id = f"cmo_{date_key}_{n:03d}"

        draft = Draft(
            id=draft_id,
            date=date_str,
            created_at=_now_iso(),
            status="draft",
            source_facts=dict(source_facts),
            draft_text=draft_text,
            fallback_text=fallback_text,
            gate_passed=gate_result.passed,
            gate_violations=list(gate_result.violations),
            rewrite_method=rewrite_method,
        )
        self._write(draft)
        return draft_id

    def get_draft(self, draft_id: str) -> Draft | None:
        return self._read(draft_id)

    def list_drafts(self, *, status: str | None = None) -> list[Draft]:
        """Return all drafts, optionally filtered by status, newest first."""
        drafts = []
        for p in sorted(self._dir.glob("cmo_*.json"), reverse=True):
            d = self._read(p.stem)
            if d is None:
                continue
            if status is not None and d.status != status:
                continue
            drafts.append(d)
        return drafts

    def approve(self, draft_id: str) -> Draft:
        """Approve a draft. Raises ValueError if not found or already published."""
        d = self._read(draft_id)
        if d is None:
            raise ValueError(f"Draft not found: {draft_id!r}")
        if d.status == "published":
            raise ValueError(f"Draft {draft_id!r} is already published")
        d.status = "approved"
        d.approved_at = _now_iso()
        self._write(d)
        return d

    def reject(self, draft_id: str, *, reason: str = "") -> Draft:
        """Reject a draft."""
        d = self._read(draft_id)
        if d is None:
            raise ValueError(f"Draft not found: {draft_id!r}")
        d.status = "rejected"
        d.rejected_at = _now_iso()
        if reason:
            d.gate_violations = d.gate_violations + [f"owner-rejected: {reason}"]
        self._write(d)
        return d

    def mark_published(self, draft_id: str, *, published_to: str) -> Draft:
        """Mark an approved draft as published. Raises if not approved."""
        d = self._read(draft_id)
        if d is None:
            raise ValueError(f"Draft not found: {draft_id!r}")
        if d.status != "approved":
            raise ValueError(f"Draft {draft_id!r} must be approved before publishing (status={d.status!r})")
        d.status = "published"
        d.published_at = _now_iso()
        d.published_to = published_to
        self._write(d)
        return d


def _now_iso() -> str:
    t = time.gmtime()
    return (
        f"{t.tm_year}-{t.tm_mon:02d}-{t.tm_mday:02d}"
        f"T{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}Z"
    )
