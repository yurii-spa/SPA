"""
spa_core/academy/api/routes/wallet.py

Sign-In With Ethereum (EIP-4361) wallet binding for the Academy sub-application.

  POST /wallet/siwe/nonce  — [auth + csrf] issue a single-use SIWE nonce + the
                             exact EIP-4361 message the wallet must sign
  POST /wallet/siwe/verify — [auth + csrf] verify the signed message, burn the
                             nonce, and bind the recovered address to the user
  GET  /wallet             — [auth]        list the caller's bound wallets

The whole SIWE check is deterministic and offline: parse the plaintext EIP-4361
message, validate domain / chain / nonce / freshness, then recover the signer
with ``eth_account`` and compare it to the claimed address. No network, no LLM.

A nonce is minted server-side, stored single-use in ``siwe_nonces`` with a 10-min
TTL, and burned (``used=1``) on the first successful verify — so a replay of the
same message is a 400. The ``idx_wallets_verified_unique`` partial index makes an
already-verified (address, chain) pair globally unique: a second user trying to
bind the same address gets a 409, never a silent hijack.

LLM FORBIDDEN in this module (auth/security-adjacent).
Academy stage 5.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from spa_core.academy.db import AcademyDB
from spa_core.academy.auth import events
from spa_core.academy.api.deps import get_current_user, get_db, require_csrf
from spa_core.utils.errors import SPAError

router = APIRouter(prefix="/wallet", tags=["academy-wallet"])

# Base mainnet. The academy binds wallets on Base only.
CHAIN_ID = 8453
CHAIN_NAME = "base"
NONCE_TTL = timedelta(minutes=10)
# How stale an "Issued At" we tolerate, and how much forward clock-skew.
ISSUED_AT_MAX_AGE = timedelta(minutes=5)
ISSUED_AT_MAX_SKEW = timedelta(minutes=2)

_PROD_DOMAIN = "earn-defi.com"
_PROD_URI = "https://earn-defi.com/academy/onboarding"
_DEV_DOMAIN = "localhost:4321"
_DEV_URI = "http://localhost:4321/academy/onboarding"

_STATEMENT = "Verify wallet ownership for Academy course"


def _is_dev() -> bool:
    return (
        os.environ.get("SPA_ACADEMY_DEV", "").strip() == "1"
        or os.environ.get("ACADEMY_DEV", "").strip() == "1"
    )


def _domain_uri() -> tuple:
    """Return (domain, uri) for the current environment (prod vs dev)."""
    if _is_dev():
        return _DEV_DOMAIN, _DEV_URI
    return _PROD_DOMAIN, _PROD_URI


def _client_ip(request: Request) -> str:
    cf = request.headers.get("cf-connecting-ip")
    if cf and cf.strip():
        return cf.strip()
    client = request.client
    return client.host if client else "unknown"


# ── SIWE primitives ──────────────────────────────────────────────────────────


def _iso(dt: datetime) -> str:
    """UTC ISO-8601 with a trailing Z (EIP-4361 date-time format)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str) -> datetime:
    """Parse an EIP-4361 date-time (…Z or …+00:00) into an aware UTC datetime."""
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def build_siwe_message(
    domain: str,
    address: str,
    uri: str,
    nonce: str,
    issued_at: str,
    expiration_time: str,
    chain_id: int = CHAIN_ID,
) -> str:
    """Render the canonical EIP-4361 plaintext message the wallet signs."""
    return (
        f"{domain} wants you to sign in with your Ethereum account:\n"
        f"{address}\n"
        f"\n"
        f"{_STATEMENT}\n"
        f"\n"
        f"URI: {uri}\n"
        f"Version: 1\n"
        f"Chain ID: {chain_id}\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {issued_at}\n"
        f"Expiration Time: {expiration_time}"
    )


def parse_siwe_message(message: str) -> dict:
    """Parse an EIP-4361 plaintext message into its structured fields.

    Returns a dict with domain, address, uri, version, chain_id, nonce,
    issued_at, expiration_time (missing fields simply absent). stdlib only —
    no regex on the numeric fields; ``chain_id`` is coerced to int when present.
    """
    lines = message.split("\n")
    out: dict = {}

    if lines:
        first = lines[0]
        marker = " wants you to sign in with your Ethereum account:"
        if marker in first:
            out["domain"] = first.split(marker, 1)[0].strip()
    if len(lines) > 1:
        addr = lines[1].strip()
        if addr:
            out["address"] = addr

    # Remaining "Key: value" lines. Only the canonical keys are picked up.
    field_keys = {
        "URI": "uri",
        "Version": "version",
        "Chain ID": "chain_id",
        "Nonce": "nonce",
        "Issued At": "issued_at",
        "Expiration Time": "expiration_time",
    }
    for line in lines[2:]:
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        dest = field_keys.get(key)
        if dest is None:
            continue
        out[dest] = value.strip()

    if "chain_id" in out:
        try:
            out["chain_id"] = int(out["chain_id"])
        except (TypeError, ValueError):
            out["chain_id"] = None
    return out


def _recover_address(message_text: str, signature: str) -> str:
    """Recover the signer address from an EIP-4361 personal_sign signature."""
    try:
        from eth_account import Account
        from eth_account.messages import encode_defunct
    except ImportError:  # pragma: no cover - dependency is in requirements.txt
        raise SPAError("eth-account not installed; pip install eth-account")
    msg = encode_defunct(text=message_text)
    return Account.recover_message(msg, signature=signature)


def _checksum(address: str) -> str:
    """Return the EIP-55 checksummed form of *address* (best-effort)."""
    try:
        from eth_utils import to_checksum_address

        return to_checksum_address(address)
    except Exception:  # pragma: no cover - eth_utils ships with eth_account
        return address


# ── request models ───────────────────────────────────────────────────────────


class NonceBody(BaseModel):
    # The address is embedded verbatim in the message the wallet signs.
    address: str = Field(..., min_length=42, max_length=42)


class VerifyBody(BaseModel):
    address: str = Field(..., min_length=42, max_length=42)
    message: str = Field(..., max_length=4000)
    signature: str = Field(..., max_length=400)


# ── routes ───────────────────────────────────────────────────────────────────


@router.post("/siwe/nonce")
def siwe_nonce(
    body: NonceBody,
    request: Request,
    db: AcademyDB = Depends(get_db),
    current_user: sqlite3.Row = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> dict:
    """Mint a single-use SIWE nonce and return the exact message to sign."""
    address = body.address.strip()
    if not (address.startswith("0x") and len(address) == 42):
        raise HTTPException(status_code=400, detail="siwe: malformed address")

    uid = current_user["id"]
    nonce = secrets.token_hex(16)
    now = datetime.now(timezone.utc)
    expires = now + NONCE_TTL
    domain, uri = _domain_uri()

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO siwe_nonces(nonce, user_id, expires_at, used) "
            "VALUES (?, ?, ?, 0)",
            (nonce, uid, _iso(expires)),
        )

    message = build_siwe_message(
        domain=domain,
        address=address,
        uri=uri,
        nonce=nonce,
        issued_at=_iso(now),
        expiration_time=_iso(expires),
    )

    events.log_event(
        db, "siwe_nonce", user_id=uid, payload={"nonce": nonce}, ip=_client_ip(request)
    )
    return {"nonce": nonce, "message": message}


@router.post("/siwe/verify")
def siwe_verify(
    body: VerifyBody,
    request: Request,
    db: AcademyDB = Depends(get_db),
    current_user: sqlite3.Row = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> dict:
    """Verify a signed EIP-4361 message and bind the recovered wallet."""
    uid = current_user["id"]
    ip = _client_ip(request)

    parsed = parse_siwe_message(body.message)

    # 1. domain must match the environment's canonical domain.
    domain, _uri = _domain_uri()
    if parsed.get("domain") != domain:
        raise HTTPException(status_code=400, detail="siwe: domain mismatch")

    # 2. chain must be Base (8453).
    if parsed.get("chain_id") != CHAIN_ID:
        raise HTTPException(status_code=400, detail="siwe: wrong chain id")

    # 3. nonce present in the message.
    nonce = parsed.get("nonce")
    if not nonce:
        raise HTTPException(status_code=400, detail="siwe: missing nonce")

    # 4. issued_at freshness (not too old, not implausibly in the future).
    issued_raw = parsed.get("issued_at")
    if not issued_raw:
        raise HTTPException(status_code=400, detail="siwe: missing issued at")
    try:
        issued_at = _parse_iso(issued_raw)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="siwe: bad issued at")
    now = datetime.now(timezone.utc)
    if issued_at < now - ISSUED_AT_MAX_AGE:
        raise HTTPException(status_code=400, detail="siwe: message too old")
    if issued_at > now + ISSUED_AT_MAX_SKEW:
        raise HTTPException(status_code=400, detail="siwe: issued in the future")

    # 5. nonce must exist for THIS user, unused and unexpired.
    with db.connect() as conn:
        nrow = conn.execute(
            "SELECT nonce, user_id, expires_at, used FROM siwe_nonces "
            "WHERE nonce = ? AND user_id = ?",
            (nonce, uid),
        ).fetchone()
    if nrow is None:
        raise HTTPException(status_code=400, detail="siwe: unknown nonce")
    if nrow["used"]:
        raise HTTPException(status_code=400, detail="siwe: nonce already used")
    try:
        nonce_exp = _parse_iso(nrow["expires_at"])
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="siwe: bad nonce expiry")
    if nonce_exp <= now:
        raise HTTPException(status_code=400, detail="siwe: nonce expired")

    # 6. signature recovery must reproduce the claimed address.
    try:
        recovered = _recover_address(body.message, body.signature)
    except HTTPException:
        raise
    except Exception:
        # Malformed signature / bad encoding — never leak a stacktrace.
        raise HTTPException(status_code=400, detail="siwe: signature recovery failed")

    if recovered.lower() != body.address.strip().lower():
        raise HTTPException(status_code=400, detail="siwe: signature does not match address")

    recovered_cs = _checksum(recovered)

    # 7 + 8 + 9. Burn the nonce and upsert the verified wallet atomically.
    with db.connect() as conn:
        # Re-check + burn inside the write txn to avoid a double-spend race.
        cur = conn.execute(
            "UPDATE siwe_nonces SET used = 1 WHERE nonce = ? AND user_id = ? AND used = 0",
            (nonce, uid),
        )
        if cur.rowcount != 1:
            raise HTTPException(status_code=400, detail="siwe: nonce already used")

        # Global uniqueness: is this address verified by a DIFFERENT user?
        clash = conn.execute(
            "SELECT user_id FROM wallets "
            "WHERE address = ? AND chain = ? AND verified_at IS NOT NULL",
            (recovered_cs, CHAIN_NAME),
        ).fetchone()
        if clash is not None and clash["user_id"] != uid:
            raise HTTPException(status_code=409, detail="siwe: address already bound")

        conn.execute(
            "INSERT INTO wallets(user_id, address, chain, verified_at) "
            "VALUES (?, ?, ?, datetime('now')) "
            "ON CONFLICT(user_id, address, chain) DO UPDATE SET "
            "verified_at = datetime('now')",
            (uid, recovered_cs, CHAIN_NAME),
        )

    events.log_event(
        db, "siwe_verify", user_id=uid, payload={"nonce": nonce}, ip=ip
    )
    events.log_event(
        db, "wallet_bind", user_id=uid, payload={"chain": CHAIN_NAME}, ip=ip
    )
    return {"ok": True, "address": recovered_cs, "chain": CHAIN_NAME}


@router.get("")
def list_wallets(
    db: AcademyDB = Depends(get_db),
    current_user: sqlite3.Row = Depends(get_current_user),
) -> list:
    """List the caller's bound wallets (verified and pending)."""
    uid = current_user["id"]
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, address, chain, label, verified_at FROM wallets "
            "WHERE user_id = ? ORDER BY id",
            (uid,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "address": r["address"],
            "chain": r["chain"],
            "label": r["label"],
            "verified_at": r["verified_at"],
            "is_verified": r["verified_at"] is not None,
        }
        for r in rows
    ]
