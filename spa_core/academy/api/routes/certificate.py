"""
spa_core/academy/api/routes/certificate.py

Completion certificate for the Academy: Real-Money Onboarding contour.

  GET  /certificate                 — [auth]        the caller's certificate
  POST /certificate/publish         — [auth + csrf] make it public + anchor it
  GET  /certificate/public/{token}  — [NO auth]     the published snapshot

Scheme:
  * A certificate exists ONLY when all 9 modules (0–8) are ``verified``. Until
    then GET /certificate is a 404 (nothing to show yet).
  * By default a certificate is PRIVATE — visible only to its authenticated
    owner via GET /certificate.
  * Publishing mints a random ``public_token``, freezes a DETERMINISTIC snapshot
    of the certificate content, hashes it (SHA-256), and anchors that hash into
    the academy's own append-only hash-chain (the ``events`` table, whose
    UPDATE/DELETE triggers make it immutable). The public snapshot is then
    readable, without auth, at /certificate/public/{token}.

Hash-chain anchoring (self-contained, no cross-domain writes):
  Each publish appends a ``cert_anchor`` event carrying
  ``{cert_hash, prev_hash, anchored_at}`` where ``prev_hash`` is the previous
  anchor's ``cert_hash`` (or ``"genesis"`` for the first). Because ``events`` is
  append-only at the DB layer, this forms a tamper-evident chain that ships in
  every daily backup (academy.db). This mirrors SPA's proof-chain pattern
  (spa_core/tournament/tournament_proof_chain.py) inside the academy's boundary.

LLM FORBIDDEN in this module.
Academy stage 9.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Path, Request

from spa_core.academy.db import AcademyDB
from spa_core.academy.auth import events
from spa_core.academy.content.modules import LESSON_IDS, MODULES
from spa_core.academy.api.deps import get_current_user, get_db, require_csrf
from spa_core.academy.onchain.verifiers import get_gas_summary

router = APIRouter(prefix="/certificate", tags=["academy-certificate"])

_NOT_COMPLETE_DETAIL = "Завершите все 9 модулей"
_PUBLIC_URL_BASE = "https://earn-defi.com/academy/onboarding/certificate"


def _client_ip(request: Request) -> str:
    cf = request.headers.get("cf-connecting-ip")
    if cf and cf.strip():
        return cf.strip()
    client = request.client
    return client.host if client else "unknown"


def _evidence_brief(ev: dict) -> dict:
    """A small, non-sensitive summary of a lesson's verified evidence blob."""
    if not isinstance(ev, dict):
        return {}
    brief: dict = {}
    for key in ("kind", "tx_hash", "chain", "amount_usdc", "approve_tx", "revoke_tx", "best_score"):
        if key in ev:
            brief[key] = ev[key]
    return brief


def _gas_usd_display(gas_summary: dict) -> str:
    """Format the estimated course-wide gas as a ``$X.XX`` string."""
    usd = gas_summary.get("total_gas_usd_est", 0) or 0
    try:
        return f"${float(usd):.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _load_state(db: AcademyDB, uid: int):
    """Return (all_verified: bool, verified_rows: dict, quiz_best: dict, wallets: list)."""
    with db.connect() as conn:
        prog = {
            r["lesson_id"]: r
            for r in conn.execute(
                "SELECT lesson_id, status, completed_at, evidence_json "
                "FROM progress WHERE user_id = ? AND status = 'verified'",
                (uid,),
            ).fetchall()
        }
        quiz_rows = conn.execute(
            "SELECT lesson_id, MAX(score) AS best FROM quiz_results "
            "WHERE user_id = ? GROUP BY lesson_id",
            (uid,),
        ).fetchall()
        wallet_rows = conn.execute(
            "SELECT address, chain, verified_at FROM wallets "
            "WHERE user_id = ? AND verified_at IS NOT NULL ORDER BY id",
            (uid,),
        ).fetchall()

    all_verified = all(lid in prog for lid in LESSON_IDS)
    quiz_best = {str(r["lesson_id"]): r["best"] for r in quiz_rows}
    wallets = [
        {"address": r["address"], "chain": r["chain"], "verified_at": r["verified_at"]}
        for r in wallet_rows
    ]
    return all_verified, prog, quiz_best, wallets


def _build_cert_core(db: AcademyDB, current_user: sqlite3.Row) -> dict:
    """Build the DETERMINISTIC certificate content (the hashed payload).

    Raises HTTPException(404) unless all 9 modules are verified. The returned
    dict is stable for a given DB state: no wall-clock, no random token — so its
    SHA-256 is reproducible and anchorable.
    """
    uid = current_user["id"]
    all_verified, prog, quiz_best, wallets = _load_state(db, uid)
    if not all_verified:
        raise HTTPException(status_code=404, detail=_NOT_COMPLETE_DETAIL)

    modules = []
    completed_ats = []
    for lid in LESSON_IDS:
        row = prog[lid]
        try:
            ev = json.loads(row["evidence_json"]) if row["evidence_json"] else {}
        except (ValueError, TypeError):
            ev = {}
        if row["completed_at"]:
            completed_ats.append(row["completed_at"])
        modules.append(
            {
                "lesson_id": lid,
                "title_ru": MODULES[lid]["title_ru"],
                "completed_at": row["completed_at"],
                "evidence": _evidence_brief(ev),
                "quiz_score": quiz_best.get(str(lid)),
            }
        )

    gas_summary = dict(get_gas_summary(db, uid))
    gas_summary["gas_usd_display"] = _gas_usd_display(gas_summary)

    return {
        "user_email": current_user["email"],
        "completed_at": max(completed_ats) if completed_ats else None,
        "modules": modules,
        "wallets": wallets,
        "gas_summary": gas_summary,
        "quiz_summary": quiz_best,
    }


def _canonical_hash(cert_core: dict) -> str:
    """SHA-256 of the deterministic (sorted-keys, compact) cert JSON."""
    blob = json.dumps(cert_core, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _latest_publication(db: AcademyDB, uid: int):
    """Return the payload of this user's most recent cert_published event, or None."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT payload_json FROM events "
            "WHERE user_id = ? AND action = 'cert_published' "
            "ORDER BY id DESC LIMIT 1",
            (uid,),
        ).fetchone()
    if row is None or not row["payload_json"]:
        return None
    try:
        return json.loads(row["payload_json"])
    except (ValueError, TypeError):
        return None


@router.get("")
def get_certificate(
    db: AcademyDB = Depends(get_db),
    current_user: sqlite3.Row = Depends(get_current_user),
) -> dict:
    """Return the caller's certificate (404 until all 9 modules are verified)."""
    cert_core = _build_cert_core(db, current_user)  # raises 404 if incomplete
    pub = _latest_publication(db, current_user["id"])
    is_public = pub is not None
    token = pub.get("public_token") if pub else None
    cert_hash = pub.get("cert_hash") if pub else None
    return {
        **cert_core,
        "is_public": is_public,
        "public_token": token,
        "public_url": f"{_PUBLIC_URL_BASE}/{token}" if token else None,
        "cert_hash": cert_hash,
    }


@router.post("/publish")
def publish_certificate(
    request: Request,
    db: AcademyDB = Depends(get_db),
    current_user: sqlite3.Row = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> dict:
    """Publish the certificate: mint a public token, snapshot + hash + anchor it.

    Idempotent: if already published, returns the SAME token/hash (200), never a
    second snapshot. Requires all 9 modules verified (else 404).
    """
    uid = current_user["id"]

    # Idempotency: an existing publication wins — same token, same hash.
    existing = _latest_publication(db, uid)
    if existing is not None:
        token = existing["public_token"]
        return {
            "public_token": token,
            "public_url": f"{_PUBLIC_URL_BASE}/{token}",
            "cert_hash": existing["cert_hash"],
            "already_published": True,
        }

    # Fresh publication. Build the deterministic snapshot + its hash.
    cert_core = _build_cert_core(db, current_user)  # raises 404 if incomplete
    public_token = secrets.token_urlsafe(24)
    cert_hash = _canonical_hash(cert_core)

    # 1. Record the publication (carries the frozen snapshot for the public view).
    events.log_event(
        db,
        "cert_published",
        user_id=uid,
        payload={
            "public_token": public_token,
            "cert_hash": cert_hash,
            "cert_data_snapshot": cert_core,
        },
        ip=_client_ip(request),
    )

    # 2. Anchor the hash into the append-only chain (prev_hash links the chain).
    with db.connect() as conn:
        prev_row = conn.execute(
            "SELECT payload_json FROM events WHERE action = 'cert_anchor' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        prev_hash = "genesis"
        if prev_row is not None and prev_row["payload_json"]:
            try:
                prev_hash = json.loads(prev_row["payload_json"]).get("cert_hash", "genesis")
            except (ValueError, TypeError):
                prev_hash = "genesis"
    events.log_event(
        db,
        "cert_anchor",
        user_id=uid,
        payload={
            "cert_hash": cert_hash,
            "prev_hash": prev_hash,
            "anchored_at": _iso_now(),
        },
        ip=_client_ip(request),
    )

    return {
        "public_token": public_token,
        "public_url": f"{_PUBLIC_URL_BASE}/{public_token}",
        "cert_hash": cert_hash,
        "already_published": False,
    }


@router.get("/public/{public_token}")
def get_public_certificate(
    public_token: str = Path(..., min_length=8, max_length=128),
    db: AcademyDB = Depends(get_db),
) -> dict:
    """Return the frozen public snapshot for *public_token* (404 if unknown).

    No authentication: a published certificate is meant to be shareable. The
    response is the snapshot captured at publish time — the same content shape as
    GET /certificate — plus its immutable ``cert_hash`` and public URL.
    """
    with db.connect() as conn:
        row = conn.execute(
            "SELECT payload_json FROM events "
            "WHERE action = 'cert_published' "
            "AND json_extract(payload_json, '$.public_token') = ? "
            "ORDER BY id DESC LIMIT 1",
            (public_token,),
        ).fetchone()
    if row is None or not row["payload_json"]:
        raise HTTPException(status_code=404, detail="certificate not found")
    try:
        payload = json.loads(row["payload_json"])
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="certificate not found")

    snapshot = payload.get("cert_data_snapshot") or {}
    return {
        **snapshot,
        "is_public": True,
        "public_token": public_token,
        "public_url": f"{_PUBLIC_URL_BASE}/{public_token}",
        "cert_hash": payload.get("cert_hash"),
    }


def _iso_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
