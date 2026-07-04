"""
spa_core/academy/api/routes/verify.py

Practice verification endpoint for the Academy sub-application.

  POST /verify/{lesson_id}  — [auth + csrf] submit proof for a lesson and, on
                              success, advance its progress to ``verified``.

Dispatch by lesson id to the deterministic on-chain verifiers in
:mod:`spa_core.academy.onchain.verifiers`:

    M0, M3, M5, M6 → require {"tx_hash": "0x…"}    (on-chain tx proof)
    M4       → {"approve_tx": "0x…", "revoke_tx": "0x…"}  (approve + revoke)
    M1       → {} — checks a verified SIWE wallet binding exists
    M2       → {} — checks the bound Base wallet holds ETH for gas
    M7       → {} — best incidents-quiz score ≥ 80%
    M8       → {} — capstone: fresh Supply+Withdraw after start + reflection note

Money-path safety: the verifiers are read-only, hold no keys, and fail-CLOSED
(RPC outage → "unavailable", never a silent pass). This router only ever writes
progress + the append-only events log; it never moves funds.

Rate limiting (10/3600 per principal) is applied by AcademyRateLimit middleware.

LLM FORBIDDEN in this module.
Academy stage 6 (M0–M3); stage 7 (M4–M8 routing).
"""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Request

from spa_core.academy.db import AcademyDB
from spa_core.academy.auth import events
from spa_core.academy.api.deps import get_current_user, get_db, require_csrf
from spa_core.academy.onchain import verifiers

router = APIRouter(prefix="/verify", tags=["academy-verify"])

# Lessons whose verification does not depend on a prior "start" action — the act
# of verifying implicitly starts them (SIWE / balance / quiz / capstone checks).
_AUTO_START = {1, 2, 7, 8}
# Statuses from which a (re)verify attempt is allowed for non-auto-start lessons.
_VERIFIABLE_FROM = {"in_progress", "submitted", "failed"}


def _client_ip(request: Request) -> str:
    cf = request.headers.get("cf-connecting-ip")
    if cf and cf.strip():
        return cf.strip()
    client = request.client
    return client.host if client else "unknown"


def _explorer_url(evidence: dict) -> str | None:
    tx = evidence.get("tx_hash")
    if not tx:
        return None
    chain = evidence.get("chain")
    if chain == "base_sepolia":
        return f"https://sepolia.basescan.org/tx/{tx}"
    return f"https://basescan.org/tx/{tx}"


def _evidence_summary(evidence: dict) -> dict:
    """Small, non-sensitive summary handed back to the client (never the raw blob)."""
    summary: dict = {}
    if evidence.get("tx_hash"):
        summary["tx_hash"] = evidence["tx_hash"]
        url = _explorer_url(evidence)
        if url:
            summary["explorer_url"] = url
    if evidence.get("chain"):
        summary["chain"] = evidence["chain"]
    if "amount_usdc" in evidence:
        summary["amount_usdc"] = evidence["amount_usdc"]
    if evidence.get("advisory_over_limit"):
        summary["advisory_over_limit"] = True
    return summary


def _run_verifier(lesson_id: int, db: AcademyDB, uid: int, started_at, body: dict):
    """Dispatch to the right verifier. Raises HTTPException(400) on a bad body."""
    if lesson_id == 0:
        tx = (body or {}).get("tx_hash")
        if not tx:
            raise HTTPException(status_code=400, detail="tx_hash required")
        return verifiers.verify_m0(db, uid, lesson_id, tx, started_at)
    if lesson_id == 1:
        return verifiers.verify_m1(db, uid, lesson_id)
    if lesson_id == 2:
        return verifiers.verify_m2(db, uid, lesson_id, started_at)
    if lesson_id == 3:
        tx = (body or {}).get("tx_hash")
        if not tx:
            raise HTTPException(status_code=400, detail="tx_hash required")
        return verifiers.verify_m3(db, uid, lesson_id, tx, started_at)
    if lesson_id == 4:
        approve_tx = (body or {}).get("approve_tx")
        revoke_tx = (body or {}).get("revoke_tx")
        if not approve_tx or not revoke_tx:
            raise HTTPException(status_code=400, detail="approve_tx and revoke_tx required")
        return verifiers.verify_m4(db, uid, lesson_id, approve_tx, revoke_tx, started_at)
    if lesson_id == 5:
        tx = (body or {}).get("tx_hash")
        if not tx:
            raise HTTPException(status_code=400, detail="tx_hash required")
        return verifiers.verify_m5(db, uid, lesson_id, tx, started_at)
    if lesson_id == 6:
        tx = (body or {}).get("tx_hash")
        if not tx:
            raise HTTPException(status_code=400, detail="tx_hash required")
        return verifiers.verify_m6(db, uid, lesson_id, tx, started_at)
    if lesson_id == 7:
        return verifiers.verify_m7(db, uid, lesson_id)
    if lesson_id == 8:
        return verifiers.verify_m8(db, uid, lesson_id, started_at)
    raise HTTPException(status_code=404, detail="unknown lesson")


@router.post("/{lesson_id}")
def verify_lesson(
    request: Request,
    lesson_id: int = Path(..., ge=0, le=8),
    body: dict = Body(default={}),
    db: AcademyDB = Depends(get_db),
    current_user: sqlite3.Row = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> dict:
    """Verify a lesson's practice proof and, on success, mark it verified."""
    uid = current_user["id"]
    ip = _client_ip(request)

    # 1. Load (or lazily start) the progress row.
    with db.connect() as conn:
        row = conn.execute(
            "SELECT status, started_at FROM progress WHERE user_id = ? AND lesson_id = ?",
            (uid, lesson_id),
        ).fetchone()

        if row is None or row["status"] == "not_started":
            if lesson_id in _AUTO_START:
                conn.execute(
                    "INSERT INTO progress(user_id, lesson_id, status, started_at) "
                    "VALUES (?, ?, 'in_progress', datetime('now')) "
                    "ON CONFLICT(user_id, lesson_id) DO UPDATE SET "
                    "status = 'in_progress', "
                    "started_at = COALESCE(progress.started_at, datetime('now'))",
                    (uid, lesson_id),
                )
                row = conn.execute(
                    "SELECT status, started_at FROM progress "
                    "WHERE user_id = ? AND lesson_id = ?",
                    (uid, lesson_id),
                ).fetchone()
            else:
                raise HTTPException(status_code=409, detail="lesson not started")
        elif row["status"] == "verified":
            raise HTTPException(status_code=409, detail="lesson already verified")
        elif row["status"] not in _VERIFIABLE_FROM:
            raise HTTPException(status_code=409, detail="lesson not verifiable in current state")

    started_at = row["started_at"]

    events.log_event(
        db, "verify_submit", user_id=uid, payload={"lesson_id": lesson_id}, ip=ip
    )

    # 2. Run the deterministic verifier.
    result = _run_verifier(lesson_id, db, uid, started_at, body)

    # 3. Persist the outcome.
    if result.status == "verified":
        evidence_json = json.dumps(result.evidence, separators=(",", ":"), sort_keys=True)
        with db.connect() as conn:
            conn.execute(
                "UPDATE progress SET status = 'verified', completed_at = datetime('now'), "
                "evidence_json = ? WHERE user_id = ? AND lesson_id = ?",
                (evidence_json, uid, lesson_id),
            )
        events.log_event(
            db, "verify_pass", user_id=uid, payload={"lesson_id": lesson_id}, ip=ip
        )
    elif result.status == "failed":
        with db.connect() as conn:
            conn.execute(
                "UPDATE progress SET status = 'failed' "
                "WHERE user_id = ? AND lesson_id = ?",
                (uid, lesson_id),
            )
        events.log_event(
            db, "verify_fail", user_id=uid, payload={"lesson_id": lesson_id}, ip=ip
        )
    # "unavailable" / "pending" leave progress untouched so the user can retry.

    return {
        "status": result.status,
        "message": result.message,
        "evidence_summary": _evidence_summary(result.evidence),
    }
