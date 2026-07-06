"""
spa_core/tests/test_academy_progress_notes_quiz.py

Integration tests for Academy stage 4 — progress, notes, and quiz endpoints.

Exercises the three new routers end-to-end via Starlette's TestClient against a
throwaway tmp-file DB. Verifies:
  - GET /progress lists all 9 modules (not_started for a fresh user)
  - POST /progress start → in_progress; a second start → 409
  - GET/PUT /notes round-trip; oversized note rejected
  - GET /quiz never leaks correct_idx; POST grades + increments attempt_n
  - M7 (hard, 80% threshold) passes at 8/10 and fails at 2/10
  - M8 (empty bank) auto-passes
  - all routes require auth (401 without a session cookie)

SPA_ACADEMY_DEV=1 so the session cookie is non-Secure and survives http://.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from spa_core.academy.db import AcademyDB
from spa_core.academy.auth import invites
from spa_core.academy.content import quiz_bank
from spa_core.academy.api.app import create_academy_app


@pytest.fixture(autouse=True)
def _dev_env(monkeypatch):
    monkeypatch.setenv("SPA_ACADEMY_DEV", "1")
    # Disable rate limiting so repeated quiz/notes calls in a test don't 429.
    monkeypatch.setenv("SPA_ACADEMY_RATE_LIMIT", "0")
    monkeypatch.delenv("SPA_TRUST_PROXY", raising=False)


@pytest.fixture()
def db_path(tmp_path):
    p = tmp_path / "academy_stage4.db"
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


@pytest.fixture()
def auth(client, invite):
    """Register a user; return the csrf token (cookie is in the client jar)."""
    r = client.post(
        "/auth/register",
        json={"email": "alice@example.com", "password": "password123", "invite_code": invite},
    )
    assert r.status_code == 200
    return r.json()["csrf_token"]


def _csrf(csrf):
    return {"X-CSRF-Token": csrf}


# ── progress ─────────────────────────────────────────────────────────────────


def test_progress_lists_nine_not_started(client, auth):
    r = client.get("/progress")
    assert r.status_code == 200
    items = r.json()["progress"]
    assert len(items) == 9
    assert all(it["status"] == "not_started" for it in items)
    assert [it["lesson_id"] for it in items] == list(range(9))


def test_progress_start_sets_in_progress(client, auth):
    r = client.post("/progress", json={"lesson_id": 0, "action": "start"}, headers=_csrf(auth))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "in_progress"
    assert body["started_at"]
    # Reflected in the list too.
    listed = client.get("/progress").json()["progress"]
    assert listed[0]["status"] == "in_progress"
    assert listed[0]["started_at"]


def test_progress_start_twice_conflicts(client, auth):
    assert client.post(
        "/progress", json={"lesson_id": 0, "action": "start"}, headers=_csrf(auth)
    ).status_code == 200
    r = client.post("/progress", json={"lesson_id": 0, "action": "start"}, headers=_csrf(auth))
    assert r.status_code == 409


def test_progress_requires_auth(client):
    assert client.get("/progress").status_code == 401


# ── notes ────────────────────────────────────────────────────────────────────


def test_notes_empty_default(client, auth):
    r = client.get("/notes/0")
    assert r.status_code == 200
    assert r.json()["text"] == ""


def test_notes_put_then_get(client, auth):
    r = client.put("/notes/0", json={"text": "hello"}, headers=_csrf(auth))
    assert r.status_code == 200
    got = client.get("/notes/0")
    assert got.status_code == 200
    assert got.json()["text"] == "hello"


def test_notes_too_long_rejected(client, auth):
    r = client.put("/notes/0", json={"text": "a" * 20001}, headers=_csrf(auth))
    assert r.status_code in (400, 422)


def test_notes_requires_auth(client):
    assert client.get("/notes/0").status_code == 401


# ── quiz ─────────────────────────────────────────────────────────────────────


def test_quiz_get_hides_correct_idx(client, auth):
    r = client.get("/quiz/0")
    assert r.status_code == 200
    questions = r.json()["questions"]
    assert len(questions) >= 5
    for q in questions:
        assert set(q.keys()) == {"id", "text", "options"}
        assert "correct_idx" not in q
        assert "explanation" not in q


def test_quiz_submit_records_attempts(client, auth):
    r1 = client.post("/quiz/0", json={"answers": [1, 1, 2, 3, 0]}, headers=_csrf(auth))
    assert r1.status_code == 200
    b1 = r1.json()
    assert b1["attempt_n"] == 1
    assert "score" in b1 and "passed" in b1
    # No correct answers leaked in feedback structure.
    assert isinstance(b1["feedback"], list)

    r2 = client.post("/quiz/0", json={"answers": [1, 1, 2, 3, 0]}, headers=_csrf(auth))
    assert r2.json()["attempt_n"] == 2


def test_quiz_m0_all_correct_passes(client, auth):
    # Build the fully-correct answer vector straight from the server bank.
    correct = [q["correct_idx"] for q in quiz_bank.QUIZ_BANK[0]]
    r = client.post("/quiz/0", json={"answers": correct}, headers=_csrf(auth))
    body = r.json()
    assert body["score"] == 100.0
    assert body["passed"] is True


def test_quiz_m7_eight_of_ten_passes(client, auth):
    bank = quiz_bank.QUIZ_BANK[7]
    assert len(bank) >= 10
    correct = [q["correct_idx"] for q in bank]
    # Corrupt exactly 2 answers → 8/10 = 80% → passes.
    answers = list(correct)
    for i in (0, 1):
        answers[i] = (answers[i] + 1) % len(bank[i]["options"])
    r = client.post("/quiz/7", json={"answers": answers}, headers=_csrf(auth))
    body = r.json()
    assert body["score"] >= 80.0
    assert body["passed"] is True


def test_quiz_m7_two_of_ten_fails(client, auth):
    bank = quiz_bank.QUIZ_BANK[7]
    correct = [q["correct_idx"] for q in bank]
    # Corrupt all but 2 → 2/10 = 20% → fails.
    answers = list(correct)
    for i in range(2, len(answers)):
        answers[i] = (answers[i] + 1) % len(bank[i]["options"])
    r = client.post("/quiz/7", json={"answers": answers}, headers=_csrf(auth))
    body = r.json()
    assert body["score"] < 80.0
    assert body["passed"] is False


def test_quiz_m8_capstone_all_correct_passes(client, auth):
    # M8 now carries a graded capstone quiz (full-loop order / chain-of-risk / exit-discipline).
    # Submitting the correct answers scores 100. Completion itself is still gated on-chain (verify.py),
    # not by this quiz — the quiz is practice/reinforcement.
    correct = [q["correct_idx"] for q in quiz_bank.QUIZ_BANK[8]]
    r = client.post("/quiz/8", json={"answers": correct}, headers=_csrf(auth))
    assert r.status_code == 200
    body = r.json()
    assert body["score"] == 100.0
    assert body["passed"] is True


def test_quiz_requires_auth(client):
    assert client.get("/quiz/0").status_code == 401
