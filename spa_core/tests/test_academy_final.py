"""
spa_core/tests/test_academy_final.py

Stage 9 integration tests — export, admin, and certificate (+publish +public
+hash-chain anchor) surfaces of the Academy sub-application.

All HTTP goes through Starlette's TestClient against a throwaway tmp-file DB. NO
network, NO real data/ dir. Rate limiting is left OFF (SPA_ACADEMY_RATE_LIMIT=0)
except where a test explicitly exercises it.

LLM FORBIDDEN in this module.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from spa_core.academy.db import AcademyDB
from spa_core.academy.auth import invites
from spa_core.academy.api.app import create_academy_app
from spa_core.academy.content.modules import LESSON_IDS


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _dev_env(monkeypatch):
    monkeypatch.setenv("SPA_ACADEMY_DEV", "1")
    monkeypatch.setenv("SPA_ACADEMY_RATE_LIMIT", "0")


@pytest.fixture()
def db_path(tmp_path):
    p = tmp_path / "academy_final.db"
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
    return invites.create_invite(db, max_uses=10)


# ── helpers ───────────────────────────────────────────────────────────────────


def _register(client, invite, email="alice@example.com", password="password123"):
    r = client.post(
        "/auth/register",
        json={"email": email, "password": password, "invite_code": invite},
    )
    assert r.status_code == 200, r.text
    return r.json()  # {ok, csrf_token, user:{...}}


def _user_id(db, email):
    with db.connect() as conn:
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    return row["id"]


def _make_owner(db, email):
    with db.connect() as conn:
        conn.execute("UPDATE users SET is_owner = 1 WHERE email = ?", (email,))


def _seed_full_completion(db, uid):
    """Mark all 9 modules verified with evidence (incl. gas), a wallet, a quiz."""
    with db.connect() as conn:
        for lid in LESSON_IDS:
            ev = {"kind": "onchain_tx", "chain": "base"}
            if lid == 6:
                ev["gas_wei"] = 21_000_000_000_000  # contributes to gas summary
                ev["tx_hash"] = "0x" + "d" * 64
            conn.execute(
                "INSERT INTO progress(user_id, lesson_id, status, started_at, "
                "completed_at, evidence_json) VALUES (?, ?, 'verified', "
                "datetime('now','-1 day'), datetime('now'), ?) "
                "ON CONFLICT(user_id, lesson_id) DO UPDATE SET status='verified', "
                "completed_at=datetime('now'), evidence_json=excluded.evidence_json",
                (uid, lid, json.dumps(ev)),
            )
        conn.execute(
            "INSERT INTO wallets(user_id, address, chain, verified_at) "
            "VALUES (?, ?, 'base', datetime('now'))",
            (uid, "0x1111111111111111111111111111111111111111"),
        )
        conn.execute(
            "INSERT INTO quiz_results(user_id, lesson_id, score, answers_json, attempt_n) "
            "VALUES (?, 7, 90.0, '[0,1,2]', 1)",
            (uid,),
        )


# ── export ────────────────────────────────────────────────────────────────────


def test_export_requires_auth(client):
    assert client.get("/export").status_code == 401


def test_export_returns_all_keys(client, invite):
    _register(client, invite)
    r = client.get("/export")
    assert r.status_code == 200
    body = r.json()
    for key in (
        "user",
        "progress",
        "notes",
        "quiz_results",
        "wallets",
        "events",
        "gas_summary",
        "exported_at",
    ):
        assert key in body, f"missing export key: {key}"
    assert body["user"]["email"] == "alice@example.com"
    assert len(body["progress"]) == 9
    assert set(body["gas_summary"]) >= {
        "total_gas_wei",
        "total_gas_eth",
        "total_gas_usd_est",
    }


def test_export_scoped_to_current_user(client, db, invite):
    # Another user's events must NOT appear in alice's export.
    _register(client, invite, email="bob@example.com")
    bob_id = _user_id(db, "bob@example.com")
    # Fresh client (jar) for alice.
    from spa_core.academy.api.app import create_academy_app  # local, same db

    _register(client, invite, email="alice@example.com")  # client now = alice
    alice_id = _user_id(db, "alice@example.com")
    body = client.get("/export").json()
    # Every event returned belongs to alice (bob's id never leaks).
    ids = {e["id"] for e in body["events"]}
    with db.connect() as conn:
        bob_event_ids = {
            r["id"]
            for r in conn.execute(
                "SELECT id FROM events WHERE user_id = ?", (bob_id,)
            ).fetchall()
        }
    assert ids.isdisjoint(bob_event_ids)
    assert alice_id != bob_id


# ── admin ─────────────────────────────────────────────────────────────────────


def test_admin_users_requires_auth(client):
    assert client.get("/admin/users").status_code == 401


def test_admin_users_non_owner_forbidden(client, invite):
    _register(client, invite)  # a normal (non-owner) user
    assert client.get("/admin/users").status_code == 403


def test_admin_users_owner_no_password_hash(client, db, invite):
    _register(client, invite, email="owner@example.com")
    _make_owner(db, "owner@example.com")
    r = client.get("/admin/users")
    assert r.status_code == 200
    users = r.json()["users"]
    assert users, "expected at least the owner user"
    for u in users:
        assert "password_hash" not in u
        assert "email" in u and "id" in u


def test_admin_progress_owner(client, db, invite):
    _register(client, invite, email="owner@example.com")
    uid = _user_id(db, "owner@example.com")
    _make_owner(db, "owner@example.com")
    _seed_full_completion(db, uid)
    r = client.get("/admin/progress")
    assert r.status_code == 200
    rows = r.json()["progress"]
    assert any(row["email"] == "owner@example.com" for row in rows)
    assert all("email" in row and "lesson_id" in row for row in rows)


def test_admin_events_owner_limit(client, db, invite):
    _register(client, invite, email="owner@example.com")
    _make_owner(db, "owner@example.com")
    r = client.get("/admin/events?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["events"], list)
    assert body["limit"] == 5
    assert len(body["events"]) <= 5


def test_admin_events_limit_clamped(client, db, invite):
    _register(client, invite, email="owner@example.com")
    _make_owner(db, "owner@example.com")
    # limit above the 1000 ceiling → 422 (query validator rejects it).
    assert client.get("/admin/events?limit=5000").status_code == 422


# ── certificate ───────────────────────────────────────────────────────────────


def test_certificate_incomplete_404(client, invite):
    _register(client, invite)
    r = client.get("/certificate")
    assert r.status_code == 404
    assert r.json()["detail"] == "Завершите все 9 модулей"


def test_certificate_complete_200(client, db, invite):
    reg = _register(client, invite)
    uid = _user_id(db, "alice@example.com")
    _seed_full_completion(db, uid)
    r = client.get("/certificate")
    assert r.status_code == 200
    body = r.json()
    assert body["user_email"] == "alice@example.com"
    assert len(body["modules"]) == 9
    assert body["is_public"] is False
    assert body["public_token"] is None
    assert body["cert_hash"] is None
    # gas_usd_display present and $-formatted.
    assert body["gas_summary"]["gas_usd_display"].startswith("$")
    assert body["gas_summary"]["gas_usd_display"].count(".") == 1


def test_certificate_publish_returns_token_and_hash(client, db, invite):
    reg = _register(client, invite)
    uid = _user_id(db, "alice@example.com")
    _seed_full_completion(db, uid)
    r = client.post("/certificate/publish", headers={"X-CSRF-Token": reg["csrf_token"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["public_token"]
    assert len(body["cert_hash"]) == 64  # sha256 hex
    assert body["public_url"].endswith(body["public_token"])


def test_publish_requires_csrf(client, db, invite):
    _register(client, invite)
    uid = _user_id(db, "alice@example.com")
    _seed_full_completion(db, uid)
    assert client.post("/certificate/publish").status_code == 403


def test_publish_idempotent(client, db, invite):
    reg = _register(client, invite)
    uid = _user_id(db, "alice@example.com")
    _seed_full_completion(db, uid)
    h = {"X-CSRF-Token": reg["csrf_token"]}
    first = client.post("/certificate/publish", headers=h).json()
    second = client.post("/certificate/publish", headers=h).json()
    assert first["public_token"] == second["public_token"]
    assert first["cert_hash"] == second["cert_hash"]
    assert second["already_published"] is True


def test_public_certificate_no_auth(client, db, invite):
    reg = _register(client, invite)
    uid = _user_id(db, "alice@example.com")
    _seed_full_completion(db, uid)
    pub = client.post(
        "/certificate/publish", headers={"X-CSRF-Token": reg["csrf_token"]}
    ).json()
    token = pub["public_token"]
    # Fresh client with NO cookies → still readable.
    anon = TestClient(create_academy_app(db_path=client.app.state.db_path))
    r = anon.get(f"/certificate/public/{token}")
    assert r.status_code == 200
    body = r.json()
    assert body["is_public"] is True
    assert body["user_email"] == "alice@example.com"
    assert body["cert_hash"] == pub["cert_hash"]
    assert len(body["modules"]) == 9


def test_public_certificate_invalid_404(client):
    assert client.get("/certificate/public/definitely-not-a-real-token").status_code == 404


def test_cert_hash_is_sha256_of_deterministic_core(client, db, invite):
    reg = _register(client, invite)
    uid = _user_id(db, "alice@example.com")
    _seed_full_completion(db, uid)
    pub = client.post(
        "/certificate/publish", headers={"X-CSRF-Token": reg["csrf_token"]}
    ).json()
    # Fetch the public snapshot and strip the publication-meta keys to recover
    # the exact deterministic core that was hashed.
    snap = client.get(f"/certificate/public/{pub['public_token']}").json()
    core = {
        k: v
        for k, v in snap.items()
        if k not in ("is_public", "public_token", "public_url", "cert_hash")
    }
    blob = json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    recomputed = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    assert recomputed == pub["cert_hash"]


def test_publish_writes_anchor_chain(client, db, invite):
    reg = _register(client, invite)
    uid = _user_id(db, "alice@example.com")
    _seed_full_completion(db, uid)
    pub = client.post(
        "/certificate/publish", headers={"X-CSRF-Token": reg["csrf_token"]}
    ).json()
    with db.connect() as conn:
        anchor = conn.execute(
            "SELECT payload_json FROM events WHERE action = 'cert_anchor' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        published = conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE action = 'cert_published'"
        ).fetchone()
    assert anchor is not None
    payload = json.loads(anchor["payload_json"])
    assert payload["cert_hash"] == pub["cert_hash"]
    assert payload["prev_hash"] == "genesis"  # first anchor in a fresh DB
    assert "anchored_at" in payload
    assert published["n"] == 1


def test_events_table_is_append_only(db):
    # The anchor chain's immutability rests on the append-only trigger: prove it.
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO events(action, payload_json) VALUES ('cert_anchor', '{}')"
        )
    import sqlite3

    # RAISE(ABORT, 'events is append-only') surfaces as an IntegrityError.
    with pytest.raises(sqlite3.IntegrityError):
        with db.connect() as conn:
            conn.execute("UPDATE events SET action = 'x' WHERE action = 'cert_anchor'")
