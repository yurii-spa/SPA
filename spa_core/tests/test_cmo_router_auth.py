"""SEC-HOTFIX-001 — the CMO router (`/api/cmo/*`) is protected at ROUTER level.

Regression guard for the fix that closed the confirmed public+unauthenticated
exposure of the mutating CMO approve/reject endpoints (SEC-VERIFY-001). The whole
`/api/cmo/*` surface now carries a router-level `Depends(require_api_key)`, which
is fail-CLOSED: with no `SPA_API_KEY` configured (the production reality today),
every CMO route returns 401 — BEFORE any handler / DraftStore mutation runs.

These tests assert:
  1. unauth  GET  /api/cmo/drafts                       → 401
  2. unauth  POST /api/cmo/drafts/{id}/approve          → 401  AND DraftStore.approve NOT called
  3. unauth  POST /api/cmo/drafts/{id}/reject           → 401  AND DraftStore.reject  NOT called
  4. unrelated public read APIs (health, portfolio)     → still 200 (not gated by the fix)
  5. WITH a valid key the CMO gate lets the request THROUGH (proves it is a real
     credential check, not a hard block — i.e. the fix is reversible/keyable)

Hermetic: enforcement is forced ON and every key source is neutralised (env
unset, Keychain stubbed to None, the APIAuth singleton reset) so the test
reflects the real fail-closed prod state regardless of the dev machine's shell
env or Keychain contents. LLM FORBIDDEN — security test, no model calls.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from spa_core.api import server
from spa_core.api.routers import cmo as cmo_router
import spa_core.api.auth as auth_mod
import spa_core.utils.keychain as keychain_mod


@pytest.fixture()
def no_key_client(tmp_path, monkeypatch):
    """Enforcement ON, NO API key anywhere → require_api_key fails CLOSED (401)."""
    monkeypatch.setenv("SPA_API_REQUIRE_AUTH", "1")
    monkeypatch.delenv("SPA_API_KEY", raising=False)
    # Neutralise the Keychain fallback and reset the cached APIAuth singleton so
    # has_key() is False no matter what this machine's Keychain holds.
    monkeypatch.setattr(keychain_mod, "get_secret", lambda *a, **k: None)
    monkeypatch.setattr(auth_mod, "_auth_instance", None, raising=False)
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c
    monkeypatch.setattr(auth_mod, "_auth_instance", None, raising=False)


@pytest.fixture()
def keyed_client(tmp_path, monkeypatch):
    """Enforcement ON WITH a valid key → a correct X-API-Key passes the gate."""
    monkeypatch.setenv("SPA_API_REQUIRE_AUTH", "1")
    monkeypatch.setenv("SPA_API_KEY", "sec-hotfix-001-test-key")
    monkeypatch.setattr(auth_mod, "_auth_instance", None, raising=False)
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c
    monkeypatch.setattr(auth_mod, "_auth_instance", None, raising=False)


# ── 1. unauth GET is rejected ────────────────────────────────────────────────
def test_unauth_get_drafts_rejected(no_key_client):
    resp = no_key_client.get("/api/cmo/drafts")
    assert resp.status_code == 401, f"expected 401, got {resp.status_code}: {resp.text[:200]}"


def test_unauth_get_single_draft_rejected(no_key_client):
    resp = no_key_client.get("/api/cmo/drafts/anything")
    assert resp.status_code == 401, f"expected 401, got {resp.status_code}: {resp.text[:200]}"


# ── 2 & 3. unauth mutations rejected BEFORE the store is touched ──────────────
def test_unauth_approve_rejected_before_mutation(no_key_client, monkeypatch):
    calls = {"approve": 0}

    def _boom(*a, **k):  # pragma: no cover - must never be reached
        calls["approve"] += 1
        raise AssertionError("DraftStore.approve reached despite missing auth")

    monkeypatch.setattr(cmo_router._store, "approve", _boom)
    resp = no_key_client.post("/api/cmo/drafts/cmo_20260716_000/approve")
    assert resp.status_code == 401, f"expected 401, got {resp.status_code}: {resp.text[:200]}"
    assert calls["approve"] == 0, "auth ran AFTER the mutation — router dep not enforced pre-handler"


def test_unauth_reject_rejected_before_mutation(no_key_client, monkeypatch):
    calls = {"reject": 0}

    def _boom(*a, **k):  # pragma: no cover - must never be reached
        calls["reject"] += 1
        raise AssertionError("DraftStore.reject reached despite missing auth")

    monkeypatch.setattr(cmo_router._store, "reject", _boom)
    resp = no_key_client.post("/api/cmo/drafts/cmo_20260716_000/reject")
    assert resp.status_code == 401, f"expected 401, got {resp.status_code}: {resp.text[:200]}"
    assert calls["reject"] == 0, "auth ran AFTER the mutation — router dep not enforced pre-handler"


# ── 4. the fix does NOT touch the public read surface ────────────────────────
@pytest.mark.parametrize("path", ["/health", "/api/portfolio"])
def test_public_read_api_still_open(no_key_client, path):
    resp = no_key_client.get(path)
    assert resp.status_code == 200, (
        f"public read {path} regressed to {resp.status_code} — the CMO hotfix must "
        f"not gate non-CMO routes"
    )


# ── 5. the gate is a real credential check, not a hard wall ──────────────────
def test_valid_key_passes_cmo_gate(keyed_client):
    resp = keyed_client.get(
        "/api/cmo/drafts", headers={"X-API-Key": "sec-hotfix-001-test-key"}
    )
    assert resp.status_code != 401, (
        f"a valid X-API-Key was rejected ({resp.status_code}) — the CMO gate is a "
        f"hard block, not a keyable auth dependency"
    )
    assert resp.status_code == 200, f"expected 200 with valid key, got {resp.status_code}"
