"""
spa_core/tests/test_academy_onchain.py

Tests for Academy stage 6 — on-chain verifiers (M0/M1/M2/M3) + /verify route.

All RPC is MOCKED (monkeypatch of spa_core.academy.onchain.rpc.call) — NO network
is ever touched. Covers: successful / reverted / stale / under-confirmed txs,
replay protection, RPC-outage fail-closed, SIWE-binding and balance checks, the
outgoing-USDC-transfer log match (+ advisory over-limit), tx-hash format
rejection, the well-known Transfer topic value, and the HTTP endpoint (auth +
progress transition).

LLM FORBIDDEN in this module.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from spa_core.academy.db import AcademyDB
from spa_core.academy.auth import invites
from spa_core.academy.api.app import create_academy_app
from spa_core.academy.onchain import rpc, verifiers
from spa_core.academy.onchain.constants import TOPIC_TRANSFER, USDC_BASE


# ── env / db fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _dev_env(monkeypatch):
    monkeypatch.setenv("SPA_ACADEMY_DEV", "1")
    monkeypatch.setenv("SPA_ACADEMY_RATE_LIMIT", "0")
    monkeypatch.delenv("SPA_TRUST_PROXY", raising=False)


@pytest.fixture()
def db_path(tmp_path):
    p = tmp_path / "academy_stage6.db"
    d = AcademyDB(db_path=str(p))
    d.run_migrations()
    return str(p)


@pytest.fixture()
def db(db_path):
    return AcademyDB(db_path=db_path)


@pytest.fixture()
def user_id(db):
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO users(email, password_hash) VALUES (?, ?)",
            ("m0@example.com", "x"),
        )
        return cur.lastrowid


def _bind_wallet(db, uid, address, chain="base"):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO wallets(user_id, address, chain, verified_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (uid, address, chain),
        )


# ── RPC mock helpers ──────────────────────────────────────────────────────────

TX = "0x" + "a" * 64
USER_ADDR = "0x1111111111111111111111111111111111111111"
DEST_ADDR = "0x2222222222222222222222222222222222222222"
PAST = "2020-01-01T00:00:00Z"
FUTURE = "2099-01-01T00:00:00Z"


def make_receipt(status="0x1", block_number=100, logs=None):
    return {
        "status": status,
        "blockNumber": hex(block_number),
        "transactionHash": TX,
        "logs": logs if logs is not None else [],
    }


def make_block(number=100, timestamp=None):
    return {
        "number": hex(number),
        "timestamp": hex(timestamp if timestamp is not None else int(time.time())),
    }


def make_transfer_log(from_addr, to_addr, amount, token=USDC_BASE):
    return {
        "address": token,
        "topics": [
            TOPIC_TRANSFER,
            verifiers._topic_for_address(from_addr),
            verifiers._topic_for_address(to_addr),
        ],
        "data": hex(amount),
    }


def install_rpc(monkeypatch, *, receipt=None, latest=110, block=None, balance=0, error=False):
    def fake(chain, method, params):
        if error:
            raise rpc.RPCError("mock outage")
        if method == "eth_getTransactionReceipt":
            return receipt
        if method == "eth_blockNumber":
            return hex(latest)
        if method == "eth_getBlockByNumber":
            return block if block is not None else make_block()
        if method == "eth_getBalance":
            return hex(balance)
        raise AssertionError(f"unexpected RPC method {method}")

    monkeypatch.setattr(rpc, "call", fake)


# ── unit: format + topic ──────────────────────────────────────────────────────


def test_is_tx_hash():
    assert verifiers.is_tx_hash(TX) is True
    assert verifiers.is_tx_hash("0x" + "a" * 63) is False  # too short
    assert verifiers.is_tx_hash("a" * 64) is False  # no 0x
    assert verifiers.is_tx_hash("0x" + "z" * 64) is False  # non-hex


def test_topic_transfer_known_value():
    # Canonical ERC-20 Transfer(address,address,uint256) topic.
    assert (
        TOPIC_TRANSFER.lower()
        == "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    )


# ── M0 ────────────────────────────────────────────────────────────────────────


def test_m0_verified(db, user_id, monkeypatch):
    install_rpc(monkeypatch, receipt=make_receipt(), latest=110, block=make_block())
    r = verifiers.verify_m0(db, user_id, 0, TX, PAST)
    assert r.status == "verified", r.message
    assert r.evidence["chain"] == "base_sepolia"
    with db.connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM used_tx_hashes WHERE tx_hash = ? AND chain = 'base_sepolia'",
            (TX,),
        ).fetchone()
    assert row is not None


def test_m0_reverted_failed(db, user_id, monkeypatch):
    install_rpc(monkeypatch, receipt=make_receipt(status="0x0"), latest=110, block=make_block())
    r = verifiers.verify_m0(db, user_id, 0, TX, PAST)
    assert r.status == "failed"


def test_m0_timestamp_before_start_failed(db, user_id, monkeypatch):
    # Block mined long ago, lesson started in the far future → stale tx.
    install_rpc(
        monkeypatch,
        receipt=make_receipt(),
        latest=110,
        block=make_block(timestamp=1000),
    )
    r = verifiers.verify_m0(db, user_id, 0, TX, FUTURE)
    assert r.status == "failed"
    assert "до начала урока" in r.message


def test_m0_insufficient_confirmations_failed(db, user_id, monkeypatch):
    install_rpc(monkeypatch, receipt=make_receipt(block_number=100), latest=102, block=make_block())
    r = verifiers.verify_m0(db, user_id, 0, TX, PAST)
    assert r.status == "failed"


def test_m0_rpc_error_unavailable(db, user_id, monkeypatch):
    install_rpc(monkeypatch, error=True)
    r = verifiers.verify_m0(db, user_id, 0, TX, PAST)
    assert r.status == "unavailable"


def test_m0_replay_failed(db, user_id, monkeypatch):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO used_tx_hashes(tx_hash, chain, user_id, lesson_id) "
            "VALUES (?, 'base_sepolia', ?, 0)",
            (TX, user_id),
        )
    install_rpc(monkeypatch, receipt=make_receipt(), latest=110, block=make_block())
    r = verifiers.verify_m0(db, user_id, 0, TX, PAST)
    assert r.status == "failed"
    assert "уже был засчитан" in r.message


def test_m0_bad_hash_rejected_before_rpc(db, user_id, monkeypatch):
    # No RPC installed: a bad hash must be rejected before any network attempt.
    def boom(*a, **k):
        raise AssertionError("RPC must not be called for a malformed hash")

    monkeypatch.setattr(rpc, "call", boom)
    r = verifiers.verify_m0(db, user_id, 0, "0xdeadbeef", PAST)
    assert r.status == "failed"
    assert "формат" in r.message


# ── M1 ────────────────────────────────────────────────────────────────────────


def test_m1_wallet_verified(db, user_id):
    _bind_wallet(db, user_id, USER_ADDR, chain="base")
    r = verifiers.verify_m1(db, user_id, 1)
    assert r.status == "verified"


def test_m1_no_wallet_failed(db, user_id):
    r = verifiers.verify_m1(db, user_id, 1)
    assert r.status == "failed"


# ── M2 ────────────────────────────────────────────────────────────────────────


def test_m2_balance_positive_verified(db, user_id, monkeypatch):
    _bind_wallet(db, user_id, USER_ADDR, chain="base")
    install_rpc(monkeypatch, balance=10 ** 15)
    r = verifiers.verify_m2(db, user_id, 2, PAST)
    assert r.status == "verified"
    assert r.evidence["wei"] == str(10 ** 15)


def test_m2_zero_balance_failed(db, user_id, monkeypatch):
    _bind_wallet(db, user_id, USER_ADDR, chain="base")
    install_rpc(monkeypatch, balance=0)
    r = verifiers.verify_m2(db, user_id, 2, PAST)
    assert r.status == "failed"


def test_m2_no_wallet_failed(db, user_id, monkeypatch):
    install_rpc(monkeypatch, balance=10 ** 15)
    r = verifiers.verify_m2(db, user_id, 2, PAST)
    assert r.status == "failed"


# ── M3 ────────────────────────────────────────────────────────────────────────


def test_m3_transfer_found_verified(db, user_id, monkeypatch):
    _bind_wallet(db, user_id, USER_ADDR, chain="base")
    log = make_transfer_log(USER_ADDR, DEST_ADDR, 100_000_000)  # 100 USDC
    install_rpc(
        monkeypatch,
        receipt=make_receipt(logs=[log]),
        latest=110,
        block=make_block(),
    )
    r = verifiers.verify_m3(db, user_id, 3, TX, PAST)
    assert r.status == "verified", r.message
    assert r.evidence["amount_usdc"] == 100.0
    assert r.evidence["from"] == USER_ADDR.lower()


def test_m3_no_transfer_failed(db, user_id, monkeypatch):
    _bind_wallet(db, user_id, USER_ADDR, chain="base")
    # A transfer FROM someone else — not the user's address.
    log = make_transfer_log(DEST_ADDR, USER_ADDR, 100_000_000)
    install_rpc(monkeypatch, receipt=make_receipt(logs=[log]), latest=110, block=make_block())
    r = verifiers.verify_m3(db, user_id, 3, TX, PAST)
    assert r.status == "failed"


def test_m3_over_limit_advisory(db, user_id, monkeypatch):
    _bind_wallet(db, user_id, USER_ADDR, chain="base")
    log = make_transfer_log(USER_ADDR, DEST_ADDR, 200_000_000)  # 200 USDC > $150
    install_rpc(monkeypatch, receipt=make_receipt(logs=[log]), latest=110, block=make_block())
    r = verifiers.verify_m3(db, user_id, 3, TX, PAST)
    assert r.status == "verified"
    assert r.evidence.get("advisory_over_limit") is True
    assert "лимит" in r.message


# ── M4–M8 stubs ────────────────────────────────────────────────────────────────


def test_m4_to_m8_pending(db, user_id):
    for fn in (verifiers.verify_m4, verifiers.verify_m5, verifiers.verify_m6,
               verifiers.verify_m7, verifiers.verify_m8):
        assert fn(db, user_id, 5).status == "pending"


# ── HTTP endpoint ──────────────────────────────────────────────────────────────


@pytest.fixture()
def client(db_path):
    return TestClient(create_academy_app(db_path=db_path))


def _register(client, db, email="http@example.com"):
    invite = invites.create_invite(db, max_uses=5)
    r = client.post(
        "/auth/register",
        json={"email": email, "password": "password123", "invite_code": invite},
    )
    assert r.status_code == 200, r.text
    return r.json()["csrf_token"]


def test_http_verify_m0_updates_progress(client, db, monkeypatch):
    csrf = _register(client, db)
    hdr = {"X-CSRF-Token": csrf}
    # Start lesson 0 (M0 is not auto-start).
    r = client.post("/progress", json={"lesson_id": 0, "action": "start"}, headers=hdr)
    assert r.status_code == 200, r.text

    # Mock the verifier so the HTTP layer is exercised without any RPC.
    from spa_core.academy.api.routes import verify as verify_mod

    def fake_m0(db_, uid, lid, tx, started):
        return verifiers.VerifyResult(
            "verified", "ok", {"tx_hash": tx, "chain": "base_sepolia", "kind": "onchain_tx"}
        )

    monkeypatch.setattr(verify_mod.verifiers, "verify_m0", fake_m0)

    r = client.post("/verify/0", json={"tx_hash": TX}, headers=hdr)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "verified"
    assert body["evidence_summary"]["tx_hash"] == TX
    assert "sepolia.basescan.org" in body["evidence_summary"]["explorer_url"]

    with db.connect() as conn:
        row = conn.execute(
            "SELECT status FROM progress WHERE lesson_id = 0"
        ).fetchone()
    assert row["status"] == "verified"


def test_http_verify_requires_auth(client):
    r = client.post("/verify/0", json={"tx_hash": TX})
    assert r.status_code == 401


def test_http_verify_m0_missing_tx_hash(client, db):
    csrf = _register(client, db)
    hdr = {"X-CSRF-Token": csrf}
    client.post("/progress", json={"lesson_id": 0, "action": "start"}, headers=hdr)
    r = client.post("/verify/0", json={}, headers=hdr)
    assert r.status_code == 400
