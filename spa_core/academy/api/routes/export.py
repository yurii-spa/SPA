"""
spa_core/academy/api/routes/export.py

Full personal-data export for the Academy sub-application (GDPR-style takeout).

  GET /export  — [auth]  return EVERYTHING this account owns as one JSON blob:
                 profile, all 9 modules' progress (full evidence), notes,
                 quiz attempts, bound wallets, this user's own audit events,
                 and the course-wide gas summary.

Scoping invariant: every row returned is filtered to ``current_user["id"]`` — a
caller can only ever export their own data. The ``password_hash`` is NEVER
included (only public profile columns). The events slice is restricted to rows
whose ``user_id`` equals the caller, so one learner can't read another's audit
trail through the export.

Rate limiting: 5 / 3600s per user_id, enforced by AcademyRateLimit (the
``/export`` bucket). A trip → 429 + Retry-After.

LLM FORBIDDEN in this module.
Academy stage 9.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request

from spa_core.academy.db import AcademyDB
from spa_core.academy.auth import events
from spa_core.academy.content.modules import LESSON_IDS
from spa_core.academy.api.deps import get_current_user, get_db
from spa_core.academy.onchain.verifiers import get_gas_summary

router = APIRouter(prefix="/export", tags=["academy-export"])


def _client_ip(request: Request) -> str:
    cf = request.headers.get("cf-connecting-ip")
    if cf and cf.strip():
        return cf.strip()
    client = request.client
    return client.host if client else "unknown"


def _parse_evidence(evidence_json) -> dict:
    """Parse the raw evidence_json blob into a dict (or {} on missing/bad JSON)."""
    if not evidence_json:
        return {}
    try:
        data = json.loads(evidence_json)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.get("")
def export_account(
    request: Request,
    db: AcademyDB = Depends(get_db),
    current_user: sqlite3.Row = Depends(get_current_user),
) -> dict:
    """Return the caller's complete academy record as a single JSON document."""
    uid = current_user["id"]

    with db.connect() as conn:
        # ── profile (public columns only — never password_hash) ──────────────
        user = {
            "email": current_user["email"],
            "created_at": current_user["created_at"],
        }

        # ── progress: all 9 modules, full parsed evidence ────────────────────
        prog_rows = {
            row["lesson_id"]: row
            for row in conn.execute(
                "SELECT lesson_id, status, started_at, completed_at, evidence_json "
                "FROM progress WHERE user_id = ?",
                (uid,),
            ).fetchall()
        }
        progress = []
        for lid in LESSON_IDS:
            row = prog_rows.get(lid)
            if row is None:
                progress.append(
                    {
                        "lesson_id": lid,
                        "status": "not_started",
                        "started_at": None,
                        "completed_at": None,
                        "evidence": {},
                    }
                )
            else:
                progress.append(
                    {
                        "lesson_id": lid,
                        "status": row["status"],
                        "started_at": row["started_at"],
                        "completed_at": row["completed_at"],
                        "evidence": _parse_evidence(row["evidence_json"]),
                    }
                )

        # ── notes: {lesson_id: text} ─────────────────────────────────────────
        notes = {
            str(r["lesson_id"]): r["text"]
            for r in conn.execute(
                "SELECT lesson_id, text FROM notes WHERE user_id = ? ORDER BY lesson_id",
                (uid,),
            ).fetchall()
        }

        # ── quiz_results: every attempt ──────────────────────────────────────
        quiz_results = [
            {
                "lesson_id": r["lesson_id"],
                "score": r["score"],
                "answers": json.loads(r["answers_json"]) if r["answers_json"] else [],
                "attempt_n": r["attempt_n"],
                "created_at": r["created_at"],
            }
            for r in conn.execute(
                "SELECT lesson_id, score, answers_json, attempt_n, created_at "
                "FROM quiz_results WHERE user_id = ? ORDER BY lesson_id, attempt_n",
                (uid,),
            ).fetchall()
        ]

        # ── wallets: addresses + verified_at ─────────────────────────────────
        wallets = [
            {
                "address": r["address"],
                "chain": r["chain"],
                "label": r["label"],
                "verified_at": r["verified_at"],
                "is_verified": r["verified_at"] is not None,
            }
            for r in conn.execute(
                "SELECT address, chain, label, verified_at FROM wallets "
                "WHERE user_id = ? ORDER BY id",
                (uid,),
            ).fetchall()
        ]

        # ── events: ONLY this user's own audit rows ──────────────────────────
        user_events = [
            {
                "id": r["id"],
                "action": r["action"],
                "payload": json.loads(r["payload_json"]) if r["payload_json"] else None,
                "created_at": r["created_at"],
            }
            for r in conn.execute(
                "SELECT id, action, payload_json, created_at FROM events "
                "WHERE user_id = ? ORDER BY id",
                (uid,),
            ).fetchall()
        ]

    gas_summary = get_gas_summary(db, uid)

    # Audit the export itself (append-only). Fire-and-forget: never fail the read.
    try:
        events.log_event(db, "export", user_id=uid, ip=_client_ip(request))
    except Exception:  # noqa: BLE001
        pass

    return {
        "user": user,
        "progress": progress,
        "notes": notes,
        "quiz_results": quiz_results,
        "wallets": wallets,
        "events": user_events,
        "gas_summary": gas_summary,
        "exported_at": _now_iso(),
    }
