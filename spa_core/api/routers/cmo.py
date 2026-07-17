"""CMO Editorial Layer API — review surface for flow B (draft → owner-approve → publish).

Endpoints:
  GET  /api/cmo/drafts            list all drafts (optionally filtered by status)
  GET  /api/cmo/drafts/{id}       get a single draft
  POST /api/cmo/drafts/{id}/approve   approve a draft
  POST /api/cmo/drafts/{id}/reject    reject a draft

No auto-publish: publish-on-approval is initiated from /blog pipeline (owner step).
LLM FORBIDDEN here. Deterministic, fail-CLOSED, stdlib-only.
"""
from __future__ import annotations

import dataclasses
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from spa_core.api.api_security import require_api_key
from spa_core.cmo.draft_store import DraftStore

# SEC-HOTFIX-001 (2026-07-17): protect the ENTIRE CMO router at router level with the
# already-wired, fail-CLOSED require_api_key dependency. With no SPA_API_KEY configured
# this returns 401 to all callers — closing the confirmed public+unauthenticated exposure
# of the mutating approve/reject endpoints (SEC-VERIFY-001). Reversible: remove
# `dependencies=[...]` below. Ref: docs/decisions / SEC-VERIFY-001 containment Option C.
router = APIRouter(tags=["cmo"], dependencies=[Depends(require_api_key)])
_store = DraftStore()


def _draft_to_dict(d: Any) -> dict:
    return dataclasses.asdict(d)


# ── GET /api/cmo/drafts ───────────────────────────────────────────────────────

@router.get("/api/cmo/drafts")
def list_drafts(status: str | None = None) -> JSONResponse:
    """List CMO drafts. Pass ?status=draft|approved|rejected|published to filter."""
    try:
        drafts = _store.list_drafts(status=status or None)
        return JSONResponse({"drafts": [_draft_to_dict(d) for d in drafts], "count": len(drafts)})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"draft-store error: {exc!r}") from exc


# ── GET /api/cmo/drafts/{draft_id} ───────────────────────────────────────────

@router.get("/api/cmo/drafts/{draft_id}")
def get_draft(draft_id: str) -> JSONResponse:
    try:
        d = _store.get_draft(draft_id)
        if d is None:
            raise HTTPException(status_code=404, detail=f"Draft not found: {draft_id!r}")
        return JSONResponse(_draft_to_dict(d))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"draft-store error: {exc!r}") from exc


# ── POST /api/cmo/drafts/{draft_id}/approve ───────────────────────────────────

@router.post("/api/cmo/drafts/{draft_id}/approve")
def approve_draft(draft_id: str) -> JSONResponse:
    """Approve a draft (owner action). Does NOT auto-publish."""
    try:
        d = _store.approve(draft_id)
        return JSONResponse({"ok": True, "draft_id": d.id, "status": d.status})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"draft-store error: {exc!r}") from exc


# ── POST /api/cmo/drafts/{draft_id}/reject ────────────────────────────────────

class RejectBody(BaseModel):
    reason: str = ""


@router.post("/api/cmo/drafts/{draft_id}/reject")
def reject_draft(draft_id: str, body: RejectBody = RejectBody()) -> JSONResponse:
    """Reject a draft with an optional reason."""
    try:
        d = _store.reject(draft_id, reason=body.reason)
        return JSONResponse({"ok": True, "draft_id": d.id, "status": d.status})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"draft-store error: {exc!r}") from exc
