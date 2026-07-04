"""
spa_core/tests/test_academy_verifiers_m4m8.py

Tests for Academy stage 7 — on-chain verifiers M4–M8 + gas accumulator.

All RPC is MOCKED (monkeypatch of spa_core.academy.onchain.rpc.call) — NO network
is ever touched. Covers:
  M4  approve+revoke (both valid / reverted / wrong order / not-approve /
      not-revoke / replay),
  M5  Aave Supply (found / not-found / advisory-over-limit / replay),
  M6  Aave Withdraw (found via user or to topic / not-found / gas recorded),
  M7  incidents quiz threshold (pass / fail / no-attempt),
  M8  capstone (all conditions / missing M6 / empty notes / gas summary),
  get_gas_summary (empty / sums across verified evidence).

LLM FORBIDDEN in this module.
"""

from __future__ import annotations

import json
import time

import pytest

from spa_core.academy.db import AcademyDB
from spa_core.academy.onchain import rpc, verifiers
from spa_core.academy.onchain.constants import (
    AAVE_POOL_BASE,
    TOPIC_APPROVAL,
    TOPIC_SUPPLY,
    TOPIC_WITHDRAW,
    USDC_BASE,
)


# ── env / db fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _dev_env(monkeypatch):
    monkeypatch.setenv("SPA_ACADEMY_DEV", "1")
    monkeypatch.setenv("SPA_ACADEMY_RATE_LIMIT", "0")


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "academy_stage7.db"
    d = AcademyDB(db_path=str(p))
    d.run_migrations()
    return d


@pytest.fixture()
def user_id(db):
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO users(email, password_hash) VALUES (?, ?)",
            ("m4@example.com", "x"),
        )
        return cur.lastrowid


USER_ADDR = "0x1111111111111111111111111111111111111111"
DEST_ADDR = "0x2222222222222222222222222222222222222222"
APPROVE_TX = "0x" + "a" * 64
REVOKE_TX = "0x" + "b" * 64
SUPPLY_TX = "0x" + "c" * 64
WITHDRAW_TX = "0x" + "d" * 64
PAST = "2020-01-01T00:00:00Z"
FUTURE = "2099-01-01T00:00:00Z"


def _bind_wallet(db, uid, address=USER_ADDR, chain="base"):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO wallets(user_id, address, chain, verified_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (uid, address, chain),
        )


def _set_progress(db, uid, lesson_id, status, evidence=None):
    ev = json.dumps(evidence) if evidence is not None else None
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO progress(user_id, lesson_id, status, evidence_json) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(user_id, lesson_id) DO UPDATE SET "
            "status = excluded.status, evidence_json = excluded.evidence_json",
            (uid, lesson_id, status, ev),
        )


def _set_note(db, uid, lesson_id, text):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO notes(user_id, lesson_id, text) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, lesson_id) DO UPDATE SET text = excluded.text",
            (uid, lesson_id, text),
        )


def _add_quiz(db, uid, lesson_id, score, attempt_n):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO quiz_results(user_id, lesson_id, score, answers_json, attempt_n) "
            "VALUES (?, ?, ?, '[]', ?)",
            (uid, lesson_id, score, attempt_n),
        )


# ── receipt / log builders ─────────────────────────────────────────────────────


def make_receipt(status="0x1", block_number=100, logs=None, gas_used=None, gas_price=None):
    r = {
        "status": status,
        "blockNumber": hex(block_number),
        "logs": logs if logs is not None else [],
    }
    if gas_used is not None:
        r["gasUsed"] = hex(gas_used)
    if gas_price is not None:
        r["effectiveGasPrice"] = hex(gas_price)
    return r


def make_block(number=100, timestamp=None):
    return {
        "number": hex(number),
        "timestamp": hex(timestamp if timestamp is not None else int(time.time())),
    }


def approval_log(owner, spender, value, token=USDC_BASE):
    return {
        "address": token,
        "topics": [
            TOPIC_APPROVAL,
            verifiers._topic_for_address(owner),
            verifiers._topic_for_address(spender),
        ],
        "data": ("0x" + "0" * 64) if value == 0 else hex(value),
    }


def supply_log(reserve, on_behalf_of, amount, user=USER_ADDR):
    # non-indexed data = (address user, uint256 amount) → 2 words.
    u = user.lower().replace("0x", "").rjust(64, "0")
    a = hex(amount)[2:].rjust(64, "0")
    return {
        "address": AAVE_POOL_BASE,
        "topics": [
            TOPIC_SUPPLY,
            verifiers._topic_for_address(reserve),
            verifiers._topic_for_address(on_behalf_of),
        ],
        "data": "0x" + u + a,
    }


def withdraw_log(reserve, user, to, amount):
    return {
        "address": AAVE_POOL_BASE,
        "topics": [
            TOPIC_WITHDRAW,
            verifiers._topic_for_address(reserve),
            verifiers._topic_for_address(user),
            verifiers._topic_for_address(to),
        ],
        "data": hex(amount),
    }


def install_rpc(monkeypatch, *, receipts=None, blocks=None, latest=110, txs=None, error=False):
    """receipts/blocks/txs are dicts keyed by tx hash (lower) / block number tag."""
    receipts = {k.lower(): v for k, v in (receipts or {}).items()}
    txs = {k.lower(): v for k, v in (txs or {}).items()}
    blocks = blocks or {}

    def fake(chain, method, params):
        if error:
            raise rpc.RPCError("mock outage")
        if method == "eth_getTransactionReceipt":
            return receipts.get(str(params[0]).lower())
        if method == "eth_blockNumber":
            return hex(latest)
        if method == "eth_getBlockByNumber":
            tag = params[0]
            num = int(tag, 16) if isinstance(tag, str) else tag
            return blocks.get(num, make_block(number=num))
        if method == "eth_getTransactionByHash":
            return txs.get(str(params[0]).lower())
        raise AssertionError(f"unexpected RPC method {method}")

    monkeypatch.setattr(rpc, "call", fake)


# ── M4 — approve + revoke ───────────────────────────────────────────────────────


def test_m4_valid(db, user_id, monkeypatch):
    _bind_wallet(db, user_id)
    r_a = make_receipt(block_number=100, logs=[approval_log(USER_ADDR, AAVE_POOL_BASE, 150_000_000)])
    r_r = make_receipt(block_number=105, logs=[approval_log(USER_ADDR, AAVE_POOL_BASE, 0)])
    install_rpc(monkeypatch, receipts={APPROVE_TX: r_a, REVOKE_TX: r_r})
    r = verifiers.verify_m4(db, user_id, 4, APPROVE_TX, REVOKE_TX, PAST)
    assert r.status == "verified", r.message
    assert r.evidence["block_approve"] == 100
    assert r.evidence["block_revoke"] == 105
    with db.connect() as conn:
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM used_tx_hashes WHERE user_id = ?", (user_id,)
        ).fetchone()["c"]
    assert n == 2


def test_m4_approve_reverted(db, user_id, monkeypatch):
    _bind_wallet(db, user_id)
    r_a = make_receipt(status="0x0", block_number=100, logs=[])
    r_r = make_receipt(block_number=105, logs=[approval_log(USER_ADDR, AAVE_POOL_BASE, 0)])
    install_rpc(monkeypatch, receipts={APPROVE_TX: r_a, REVOKE_TX: r_r})
    r = verifiers.verify_m4(db, user_id, 4, APPROVE_TX, REVOKE_TX, PAST)
    assert r.status == "failed"


def test_m4_revoke_before_approve(db, user_id, monkeypatch):
    _bind_wallet(db, user_id)
    r_a = make_receipt(block_number=110, logs=[approval_log(USER_ADDR, AAVE_POOL_BASE, 150_000_000)])
    r_r = make_receipt(block_number=105, logs=[approval_log(USER_ADDR, AAVE_POOL_BASE, 0)])
    install_rpc(monkeypatch, receipts={APPROVE_TX: r_a, REVOKE_TX: r_r}, latest=200)
    r = verifiers.verify_m4(db, user_id, 4, APPROVE_TX, REVOKE_TX, PAST)
    assert r.status == "failed"
    assert "после approve" in r.message


def test_m4_approve_value_zero(db, user_id, monkeypatch):
    # A zero-value log in the "approve" tx is not a real approval.
    _bind_wallet(db, user_id)
    r_a = make_receipt(block_number=100, logs=[approval_log(USER_ADDR, AAVE_POOL_BASE, 0)])
    r_r = make_receipt(block_number=105, logs=[approval_log(USER_ADDR, AAVE_POOL_BASE, 0)])
    install_rpc(monkeypatch, receipts={APPROVE_TX: r_a, REVOKE_TX: r_r})
    r = verifiers.verify_m4(db, user_id, 4, APPROVE_TX, REVOKE_TX, PAST)
    assert r.status == "failed"
    assert "approve" in r.message.lower()


def test_m4_revoke_value_nonzero(db, user_id, monkeypatch):
    _bind_wallet(db, user_id)
    r_a = make_receipt(block_number=100, logs=[approval_log(USER_ADDR, AAVE_POOL_BASE, 150_000_000)])
    r_r = make_receipt(block_number=105, logs=[approval_log(USER_ADDR, AAVE_POOL_BASE, 42)])
    install_rpc(monkeypatch, receipts={APPROVE_TX: r_a, REVOKE_TX: r_r})
    r = verifiers.verify_m4(db, user_id, 4, APPROVE_TX, REVOKE_TX, PAST)
    assert r.status == "failed"
    assert "revoke" in r.message.lower()


def test_m4_replay(db, user_id, monkeypatch):
    _bind_wallet(db, user_id)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO used_tx_hashes(tx_hash, chain, user_id, lesson_id) "
            "VALUES (?, 'base', ?, 4)",
            (APPROVE_TX, user_id),
        )
    r_a = make_receipt(block_number=100, logs=[approval_log(USER_ADDR, AAVE_POOL_BASE, 150_000_000)])
    r_r = make_receipt(block_number=105, logs=[approval_log(USER_ADDR, AAVE_POOL_BASE, 0)])
    install_rpc(monkeypatch, receipts={APPROVE_TX: r_a, REVOKE_TX: r_r})
    r = verifiers.verify_m4(db, user_id, 4, APPROVE_TX, REVOKE_TX, PAST)
    assert r.status == "failed"
    assert "засчитан" in r.message


def test_m4_same_tx_rejected(db, user_id, monkeypatch):
    _bind_wallet(db, user_id)
    install_rpc(monkeypatch, receipts={})
    r = verifiers.verify_m4(db, user_id, 4, APPROVE_TX, APPROVE_TX, PAST)
    assert r.status == "failed"
    assert "разными" in r.message


# ── M5 — Aave supply ────────────────────────────────────────────────────────────


def test_m5_verified(db, user_id, monkeypatch):
    _bind_wallet(db, user_id)
    log = supply_log(USDC_BASE, USER_ADDR, 100_000_000)  # 100 USDC
    install_rpc(monkeypatch, receipts={SUPPLY_TX: make_receipt(logs=[log])})
    r = verifiers.verify_m5(db, user_id, 5, SUPPLY_TX, PAST)
    assert r.status == "verified", r.message
    assert r.evidence["amount_usdc"] == 100.0
    assert r.evidence["kind"] == "aave_supply"


def test_m5_no_supply_log(db, user_id, monkeypatch):
    _bind_wallet(db, user_id)
    # Supply on behalf of someone else — not the user.
    log = supply_log(USDC_BASE, DEST_ADDR, 100_000_000)
    install_rpc(monkeypatch, receipts={SUPPLY_TX: make_receipt(logs=[log])})
    r = verifiers.verify_m5(db, user_id, 5, SUPPLY_TX, PAST)
    assert r.status == "failed"


def test_m5_over_limit_advisory(db, user_id, monkeypatch):
    _bind_wallet(db, user_id)
    log = supply_log(USDC_BASE, USER_ADDR, 200_000_000)  # 200 USDC > $150
    install_rpc(monkeypatch, receipts={SUPPLY_TX: make_receipt(logs=[log])})
    r = verifiers.verify_m5(db, user_id, 5, SUPPLY_TX, PAST)
    assert r.status == "verified"
    assert r.evidence.get("advisory_over_limit") is True
    assert "лимит" in r.message


def test_m5_replay(db, user_id, monkeypatch):
    _bind_wallet(db, user_id)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO used_tx_hashes(tx_hash, chain, user_id, lesson_id) "
            "VALUES (?, 'base', ?, 5)",
            (SUPPLY_TX, user_id),
        )
    log = supply_log(USDC_BASE, USER_ADDR, 100_000_000)
    install_rpc(monkeypatch, receipts={SUPPLY_TX: make_receipt(logs=[log])})
    r = verifiers.verify_m5(db, user_id, 5, SUPPLY_TX, PAST)
    assert r.status == "failed"


# ── M6 — Aave withdraw ──────────────────────────────────────────────────────────


def test_m6_verified_via_user_topic(db, user_id, monkeypatch):
    _bind_wallet(db, user_id)
    log = withdraw_log(USDC_BASE, USER_ADDR, DEST_ADDR, 100_000_000)
    receipt = make_receipt(logs=[log], gas_used=210000, gas_price=1_000_000_000)
    install_rpc(monkeypatch, receipts={WITHDRAW_TX: receipt})
    r = verifiers.verify_m6(db, user_id, 6, WITHDRAW_TX, PAST)
    assert r.status == "verified", r.message
    assert r.evidence["gas_wei"] == 210000 * 1_000_000_000


def test_m6_verified_via_to_topic(db, user_id, monkeypatch):
    _bind_wallet(db, user_id)
    # user appears as `to` (topic3), a relayer as `user` (topic2).
    log = withdraw_log(USDC_BASE, DEST_ADDR, USER_ADDR, 100_000_000)
    install_rpc(monkeypatch, receipts={WITHDRAW_TX: make_receipt(logs=[log], gas_used=1, gas_price=1)})
    r = verifiers.verify_m6(db, user_id, 6, WITHDRAW_TX, PAST)
    assert r.status == "verified", r.message


def test_m6_no_withdraw_log(db, user_id, monkeypatch):
    _bind_wallet(db, user_id)
    log = withdraw_log(USDC_BASE, DEST_ADDR, DEST_ADDR, 100_000_000)
    install_rpc(monkeypatch, receipts={WITHDRAW_TX: make_receipt(logs=[log])})
    r = verifiers.verify_m6(db, user_id, 6, WITHDRAW_TX, PAST)
    assert r.status == "failed"


def test_m6_gas_from_tx_gasprice(db, user_id, monkeypatch):
    # No effectiveGasPrice on the receipt → fall back to the tx's gasPrice.
    _bind_wallet(db, user_id)
    log = withdraw_log(USDC_BASE, USER_ADDR, USER_ADDR, 100_000_000)
    receipt = make_receipt(logs=[log], gas_used=100000)  # no gas_price
    install_rpc(
        monkeypatch,
        receipts={WITHDRAW_TX: receipt},
        txs={WITHDRAW_TX: {"gasPrice": hex(2_000_000_000)}},
    )
    r = verifiers.verify_m6(db, user_id, 6, WITHDRAW_TX, PAST)
    assert r.status == "verified", r.message
    assert r.evidence["gas_wei"] == 100000 * 2_000_000_000


# ── M7 — incidents quiz ─────────────────────────────────────────────────────────


def test_m7_pass(db, user_id):
    _add_quiz(db, user_id, 7, 85.0, 1)
    r = verifiers.verify_m7(db, user_id, 7)
    assert r.status == "verified"
    assert r.evidence["best_score"] == 85.0


def test_m7_below_threshold(db, user_id):
    _add_quiz(db, user_id, 7, 70.0, 1)
    r = verifiers.verify_m7(db, user_id, 7)
    assert r.status == "failed"
    assert "80" in r.message


def test_m7_no_attempt(db, user_id):
    r = verifiers.verify_m7(db, user_id, 7)
    assert r.status == "failed"


def test_m7_best_of_multiple(db, user_id):
    _add_quiz(db, user_id, 7, 60.0, 1)
    _add_quiz(db, user_id, 7, 90.0, 2)
    r = verifiers.verify_m7(db, user_id, 7)
    assert r.status == "verified"
    assert r.evidence["best_score"] == 90.0
    assert r.evidence["attempt_count"] == 2


# ── M8 — capstone ───────────────────────────────────────────────────────────────


def _capstone_setup(db, uid, *, m5=True, m6=True, note="Мне было сложно ждать подтверждений."):
    now = int(time.time())
    if m5:
        _set_progress(db, uid, 5, "verified", {"block": 100, "timestamp": now, "gas_wei": 5})
    if m6:
        _set_progress(db, uid, 6, "verified", {"block": 105, "timestamp": now + 60, "gas_wei": 7})
    if note is not None:
        _set_note(db, uid, 8, note)


def test_m8_verified(db, user_id):
    _capstone_setup(db, user_id)
    r = verifiers.verify_m8(db, user_id, 8, PAST)
    assert r.status == "verified", r.message
    assert r.evidence["gas_total_wei"] == 12
    assert r.evidence["notes_length"] > 0
    assert r.evidence["gas_total_usd_est"] == round(12 / 1e18 * 2500, 4)


def test_m8_missing_m6(db, user_id):
    _capstone_setup(db, user_id, m6=False)
    r = verifiers.verify_m8(db, user_id, 8, PAST)
    assert r.status == "failed"
    assert "M6" in r.message


def test_m8_empty_notes(db, user_id):
    _capstone_setup(db, user_id, note="   ")
    r = verifiers.verify_m8(db, user_id, 8, PAST)
    assert r.status == "failed"
    assert "рефлекси" in r.message.lower()


def test_m8_supply_before_start(db, user_id):
    # M5 evidence timestamp is BEFORE the capstone started → not a fresh cycle.
    _set_progress(db, user_id, 5, "verified", {"block": 100, "timestamp": 1000, "gas_wei": 5})
    _set_progress(db, user_id, 6, "verified", {"block": 105, "timestamp": 2000, "gas_wei": 7})
    _set_note(db, user_id, 8, "reflection")
    r = verifiers.verify_m8(db, user_id, 8, FUTURE)
    assert r.status == "failed"
    assert "капстоуна" in r.message


# ── get_gas_summary ─────────────────────────────────────────────────────────────


def test_gas_summary_empty(db, user_id):
    s = verifiers.get_gas_summary(db, user_id)
    assert s == {"total_gas_wei": 0, "total_gas_eth": 0.0, "total_gas_usd_est": 0.0}


def test_gas_summary_sums(db, user_id):
    _set_progress(db, user_id, 3, "verified", {"gas_wei": 1_000_000_000_000_000})
    _set_progress(db, user_id, 6, "verified", {"gas_wei": 2_000_000_000_000_000})
    # A non-verified row must NOT be counted.
    _set_progress(db, user_id, 5, "failed", {"gas_wei": 9_999})
    s = verifiers.get_gas_summary(db, user_id)
    assert s["total_gas_wei"] == 3_000_000_000_000_000
    assert s["total_gas_eth"] == pytest.approx(0.003)
    assert s["total_gas_usd_est"] == pytest.approx(0.003 * 2500)


def test_gas_summary_ignores_malformed(db, user_id):
    _set_progress(db, user_id, 6, "verified", {"gas_wei": 5})
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO progress(user_id, lesson_id, status, evidence_json) "
            "VALUES (?, 5, 'verified', 'not json')",
            (user_id,),
        )
    s = verifiers.get_gas_summary(db, user_id)
    assert s["total_gas_wei"] == 5


# ── HTTP routing (new stage-7 branches) ─────────────────────────────────────────


@pytest.fixture()
def client(db):
    from fastapi.testclient import TestClient
    from spa_core.academy.api.app import create_academy_app

    return TestClient(create_academy_app(db_path=db.db_path))


def _register(client, db):
    from spa_core.academy.auth import invites

    invite = invites.create_invite(db, max_uses=5)
    r = client.post(
        "/auth/register",
        json={"email": "http7@example.com", "password": "password123", "invite_code": invite},
    )
    assert r.status_code == 200, r.text
    return r.json()["csrf_token"]


def test_http_m4_missing_body_400(client, db):
    csrf = _register(client, db)
    hdr = {"X-CSRF-Token": csrf}
    client.post("/progress", json={"lesson_id": 4, "action": "start"}, headers=hdr)
    r = client.post("/verify/4", json={"approve_tx": APPROVE_TX}, headers=hdr)
    assert r.status_code == 400


def test_http_m7_no_body_routes(client, db, monkeypatch):
    csrf = _register(client, db)
    hdr = {"X-CSRF-Token": csrf}
    from spa_core.academy.api.routes import verify as verify_mod

    def fake_m7(db_, uid, lid):
        return verifiers.VerifyResult("verified", "ok", {"best_score": 100})

    monkeypatch.setattr(verify_mod.verifiers, "verify_m7", fake_m7)
    r = client.post("/verify/7", json={}, headers=hdr)  # M7 auto-starts
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "verified"
