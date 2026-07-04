"""
spa_core/tests/test_academy_siwe.py

Integration tests for Academy stage 5 — SIWE (Sign-In With Ethereum, EIP-4361)
wallet binding.

Exercises the /wallet router end-to-end against a throwaway tmp-file DB with a
deterministic test key (NO network, offline signature). Verifies:
  - POST /wallet/siwe/nonce mints a nonce and persists it single-use
  - POST /wallet/siwe/verify with a correct signature binds & verifies the wallet
  - GET /wallet lists the bound (checksummed) address
  - replay of the same nonce → 400, expired nonce → 400
  - wrong signer / wrong chain / wrong domain → 400
  - auth + CSRF are enforced (401 / 403)
  - a second user binding the same address → 409
  - parse_siwe_message round-trips build_siwe_message

SPA_ACADEMY_DEV=1 so the session cookie is non-Secure and the SIWE domain is the
Astro dev origin (localhost:4321).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from spa_core.academy.db import AcademyDB
from spa_core.academy.auth import invites
from spa_core.academy.api.app import create_academy_app
from spa_core.academy.api.routes import wallet as wallet_mod

eth_account = pytest.importorskip("eth_account")


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _dev_env(monkeypatch):
    monkeypatch.setenv("SPA_ACADEMY_DEV", "1")
    monkeypatch.setenv("SPA_ACADEMY_RATE_LIMIT", "0")
    monkeypatch.delenv("SPA_TRUST_PROXY", raising=False)


@pytest.fixture()
def db_path(tmp_path):
    p = tmp_path / "academy_stage5.db"
    d = AcademyDB(db_path=str(p))
    d.run_migrations()
    return str(p)


@pytest.fixture()
def db(db_path):
    return AcademyDB(db_path=db_path)


@pytest.fixture()
def client(db_path):
    return TestClient(create_academy_app(db_path=db_path))


@pytest.fixture()
def invite(db):
    return invites.create_invite(db, max_uses=5)


def _register(client, invite, email="alice@example.com"):
    r = client.post(
        "/auth/register",
        json={"email": email, "password": "password123", "invite_code": invite},
    )
    assert r.status_code == 200, r.text
    return r.json()["csrf_token"]


@pytest.fixture()
def auth(client, invite):
    return _register(client, invite)


@pytest.fixture()
def test_wallet():
    from eth_account import Account

    return Account.from_key("0x" + "1" * 64)


@pytest.fixture()
def other_wallet():
    from eth_account import Account

    return Account.from_key("0x" + "2" * 64)


def _csrf(csrf):
    return {"X-CSRF-Token": csrf}


def sign_message(account, message_text: str) -> str:
    from eth_account.messages import encode_defunct

    msg = encode_defunct(text=message_text)
    signed = account.sign_message(msg)
    return "0x" + signed.signature.hex().removeprefix("0x")


def _get_nonce(client, csrf, address):
    r = client.post(
        "/wallet/siwe/nonce", json={"address": address}, headers=_csrf(csrf)
    )
    assert r.status_code == 200, r.text
    return r.json()


# ── nonce ────────────────────────────────────────────────────────────────────


def test_nonce_returns_nonce_and_persists(client, db, auth, test_wallet):
    body = _get_nonce(client, auth, test_wallet.address)
    assert "nonce" in body and body["nonce"]
    assert "message" in body and test_wallet.address in body["message"]

    with db.connect() as conn:
        row = conn.execute(
            "SELECT nonce, used FROM siwe_nonces WHERE nonce = ?", (body["nonce"],)
        ).fetchone()
    assert row is not None
    assert row["used"] == 0


def test_nonce_requires_csrf(client, auth, test_wallet):
    r = client.post("/wallet/siwe/nonce", json={"address": test_wallet.address})
    assert r.status_code == 403


# ── verify happy path ────────────────────────────────────────────────────────


def test_verify_valid_signature_binds_wallet(client, db, auth, test_wallet):
    body = _get_nonce(client, auth, test_wallet.address)
    sig = sign_message(test_wallet, body["message"])
    r = client.post(
        "/wallet/siwe/verify",
        json={"address": test_wallet.address, "message": body["message"], "signature": sig},
        headers=_csrf(auth),
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] is True
    assert out["chain"] == "base"
    assert out["address"].lower() == test_wallet.address.lower()

    with db.connect() as conn:
        w = conn.execute(
            "SELECT address, chain, verified_at FROM wallets WHERE address = ?",
            (out["address"],),
        ).fetchone()
    assert w is not None
    assert w["verified_at"] is not None
    assert w["chain"] == "base"


def test_get_wallet_lists_bound_address(client, auth, test_wallet):
    body = _get_nonce(client, auth, test_wallet.address)
    sig = sign_message(test_wallet, body["message"])
    client.post(
        "/wallet/siwe/verify",
        json={"address": test_wallet.address, "message": body["message"], "signature": sig},
        headers=_csrf(auth),
    )
    r = client.get("/wallet")
    assert r.status_code == 200
    wallets = r.json()
    assert isinstance(wallets, list)
    assert len(wallets) == 1
    w = wallets[0]
    assert w["address"].lower() == test_wallet.address.lower()
    assert w["is_verified"] is True
    assert w["chain"] == "base"


# ── replay / expiry / bad inputs ─────────────────────────────────────────────


def test_verify_replay_same_nonce_fails(client, auth, test_wallet):
    body = _get_nonce(client, auth, test_wallet.address)
    sig = sign_message(test_wallet, body["message"])
    payload = {"address": test_wallet.address, "message": body["message"], "signature": sig}
    r1 = client.post("/wallet/siwe/verify", json=payload, headers=_csrf(auth))
    assert r1.status_code == 200
    r2 = client.post("/wallet/siwe/verify", json=payload, headers=_csrf(auth))
    assert r2.status_code == 400
    assert "used" in r2.json()["detail"]


def test_verify_expired_nonce_fails(client, db, auth, test_wallet):
    body = _get_nonce(client, auth, test_wallet.address)
    # Force the stored nonce to have already expired.
    with db.connect() as conn:
        conn.execute(
            "UPDATE siwe_nonces SET expires_at = ? WHERE nonce = ?",
            ("2000-01-01T00:00:00Z", body["nonce"]),
        )
    sig = sign_message(test_wallet, body["message"])
    r = client.post(
        "/wallet/siwe/verify",
        json={"address": test_wallet.address, "message": body["message"], "signature": sig},
        headers=_csrf(auth),
    )
    assert r.status_code == 400
    assert "expired" in r.json()["detail"]


def test_verify_wrong_signer_fails(client, auth, test_wallet, other_wallet):
    body = _get_nonce(client, auth, test_wallet.address)
    # Sign with a DIFFERENT key than the claimed address.
    sig = sign_message(other_wallet, body["message"])
    r = client.post(
        "/wallet/siwe/verify",
        json={"address": test_wallet.address, "message": body["message"], "signature": sig},
        headers=_csrf(auth),
    )
    assert r.status_code == 400
    assert "match" in r.json()["detail"]


def test_verify_wrong_chain_id_fails(client, auth, test_wallet):
    body = _get_nonce(client, auth, test_wallet.address)
    tampered = body["message"].replace("Chain ID: 8453", "Chain ID: 1")
    sig = sign_message(test_wallet, tampered)
    r = client.post(
        "/wallet/siwe/verify",
        json={"address": test_wallet.address, "message": tampered, "signature": sig},
        headers=_csrf(auth),
    )
    assert r.status_code == 400
    assert "chain" in r.json()["detail"]


def test_verify_wrong_domain_fails(client, auth, test_wallet):
    body = _get_nonce(client, auth, test_wallet.address)
    tampered = body["message"].replace("localhost:4321 wants", "evil.example wants")
    sig = sign_message(test_wallet, tampered)
    r = client.post(
        "/wallet/siwe/verify",
        json={"address": test_wallet.address, "message": tampered, "signature": sig},
        headers=_csrf(auth),
    )
    assert r.status_code == 400
    assert "domain" in r.json()["detail"]


# ── auth / csrf ──────────────────────────────────────────────────────────────


def test_verify_requires_auth(client, test_wallet):
    # No registration → no session cookie.
    r = client.post(
        "/wallet/siwe/verify",
        json={"address": test_wallet.address, "message": "x", "signature": "0x00"},
    )
    assert r.status_code == 401


def test_verify_requires_csrf(client, auth, test_wallet):
    body = _get_nonce(client, auth, test_wallet.address)
    sig = sign_message(test_wallet, body["message"])
    r = client.post(
        "/wallet/siwe/verify",
        json={"address": test_wallet.address, "message": body["message"], "signature": sig},
    )
    assert r.status_code == 403


# ── global uniqueness ────────────────────────────────────────────────────────


def test_same_address_second_user_conflicts(client, db, auth, test_wallet):
    # User A binds the wallet.
    body = _get_nonce(client, auth, test_wallet.address)
    sig = sign_message(test_wallet, body["message"])
    r1 = client.post(
        "/wallet/siwe/verify",
        json={"address": test_wallet.address, "message": body["message"], "signature": sig},
        headers=_csrf(auth),
    )
    assert r1.status_code == 200

    # User B (fresh client → fresh cookie jar) tries to bind the SAME address.
    client_b = TestClient(create_academy_app(db_path=db.db_path))
    invite_b = invites.create_invite(db, max_uses=5)
    csrf_b = _register(client_b, invite_b, email="bob@example.com")
    body_b = _get_nonce(client_b, csrf_b, test_wallet.address)
    sig_b = sign_message(test_wallet, body_b["message"])
    r2 = client_b.post(
        "/wallet/siwe/verify",
        json={"address": test_wallet.address, "message": body_b["message"], "signature": sig_b},
        headers=_csrf(csrf_b),
    )
    assert r2.status_code == 409
    assert "already bound" in r2.json()["detail"]


# ── parser round-trip ────────────────────────────────────────────────────────


def test_parse_siwe_message_roundtrip():
    message = wallet_mod.build_siwe_message(
        domain="earn-defi.com",
        address="0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A",
        uri="https://earn-defi.com/academy/onboarding",
        nonce="deadbeefdeadbeefdeadbeefdeadbeef",
        issued_at="2026-07-04T12:00:00Z",
        expiration_time="2026-07-04T12:10:00Z",
    )
    parsed = wallet_mod.parse_siwe_message(message)
    assert parsed["domain"] == "earn-defi.com"
    assert parsed["address"] == "0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A"
    assert parsed["uri"] == "https://earn-defi.com/academy/onboarding"
    assert parsed["chain_id"] == 8453
    assert parsed["nonce"] == "deadbeefdeadbeefdeadbeefdeadbeef"
    assert parsed["issued_at"] == "2026-07-04T12:00:00Z"
    assert parsed["expiration_time"] == "2026-07-04T12:10:00Z"
