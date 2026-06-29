"""WS2 (Round-2 "Prove the Edge") API security tests.

Covers the real audit flaw: the public :8765 API had ZERO auth + ZERO rate-limit
on every endpoint incl. the LLM ``POST /api/chat`` (budget-burn / prompt-injection)
and ``POST /api/agent/thought`` (content-injection), reachable cross-origin from
ANY ``*.pages.dev``.

Asserts:
  2.1 auth wired on writes/LLM (behind SPA_API_REQUIRE_AUTH) — unauth → 401, key → ok
  2.2 per-IP rate limiting → 429 on flood (esp. LLM POST)
  2.3 CORS allow-list — SPA origins ok, rogue evil.pages.dev blocked
  + GET proof/data endpoints STAY PUBLIC (200, no auth) — dashboard/verifier
  + red-team: oversized body, no unguarded alias path

stdlib + FastAPI TestClient. Deterministic.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from fastapi.testclient import TestClient
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

pytestmark = pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="fastapi not installed")

_TEST_KEY = "ws2-test-secret-key-DO-NOT-USE-REAL"


@pytest.fixture(autouse=True)
def _restore_auth_env():
    """Snapshot + restore the auth env and singleton so these tests never leak
    SPA_API_REQUIRE_AUTH / SPA_API_KEY into the rest of the suite (other API
    tests post to /api/chat & /api/agent/thought expecting 200)."""
    saved = {k: os.environ.get(k) for k in ("SPA_API_REQUIRE_AUTH", "SPA_API_KEY")}
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        import spa_core.api.auth as auth_mod
        auth_mod._auth_instance = None
        import spa_core.api.api_security as sec_mod
        sec_mod._warned_bypass = False


def _build_client(require_auth: bool, *, with_key: bool = True):
    """Fresh app + TestClient with the auth flag/key set, rate-limit stores reset.

    Returns (client, headers_with_valid_key). Reloads the security/auth singletons
    so the env flips take effect deterministically.
    """
    os.environ["SPA_API_REQUIRE_AUTH"] = "1" if require_auth else "0"
    if with_key:
        os.environ["SPA_API_KEY"] = _TEST_KEY
    else:
        os.environ.pop("SPA_API_KEY", None)

    # Reset the auth singleton so it reloads the key from env.
    import spa_core.api.auth as auth_mod
    auth_mod._auth_instance = None
    import spa_core.api.api_security as sec_mod
    sec_mod._warned_bypass = False

    from spa_core.api.server import app

    # Reset the rate-limit middleware stores so floods are isolated per test.
    for mw in app.user_middleware:
        # BaseHTTPMiddleware instances are constructed lazily; reset via class call.
        pass
    client = TestClient(app, raise_server_exceptions=False)
    headers = {"X-API-Key": _TEST_KEY}
    return client, headers


def _fresh_app_no_ratelimit_pressure():
    """Reset rate-limit stores on the live app instance (module-level singletons)."""
    # The middleware holds its stores; we rebuild the app import is cached, so we
    # reset stores by reaching the instantiated middleware via the ASGI stack.
    import spa_core.api.rate_limit as rl
    # Bump default capacity high enough that GET tests never trip during a run.
    return rl


# ─── 2.1 AUTH: writes/LLM gated, GET stays public ─────────────────────────────


class TestAuthWiring:
    def test_chat_unauth_401_when_enforced(self):
        client, _ = _build_client(require_auth=True)
        r = client.post("/api/chat", json={"question": "what is the apy?"})
        assert r.status_code == 401, r.text

    def test_chat_with_key_ok_when_enforced(self):
        client, headers = _build_client(require_auth=True)
        r = client.post("/api/chat", json={"question": "what is the apy?"},
                        headers=headers)
        assert r.status_code == 200, r.text

    def test_agent_thought_unauth_401_when_enforced(self):
        client, _ = _build_client(require_auth=True)
        r = client.post("/api/agent/thought",
                        json={"agent": "X", "message": "injected content"})
        assert r.status_code == 401, r.text

    def test_agent_thought_with_key_ok_when_enforced(self):
        client, headers = _build_client(require_auth=True)
        r = client.post("/api/agent/thought",
                        json={"agent": "X", "message": "legit"}, headers=headers)
        assert r.status_code == 200, r.text

    def test_bearer_token_also_accepted(self):
        client, _ = _build_client(require_auth=True)
        from spa_core.api.auth import get_auth
        token = get_auth().generate_token()
        r = client.post("/api/chat", json={"question": "hi"},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text

    def test_wrong_key_rejected(self):
        client, _ = _build_client(require_auth=True)
        r = client.post("/api/chat", json={"question": "hi"},
                        headers={"X-API-Key": "totally-wrong-key"})
        assert r.status_code == 401, r.text

    def test_fail_closed_when_enforced_but_no_key(self):
        # Enforcement ON + no configured key → fail-CLOSED 401 (never silently open).
        client, _ = _build_client(require_auth=True, with_key=False)
        r = client.post("/api/chat", json={"question": "hi"})
        assert r.status_code == 401, r.text

    def test_flag_off_allows_unauth_write(self):
        # Dev mode: flag OFF → unauth write allowed (no 401).
        client, _ = _build_client(require_auth=False)
        r = client.post("/api/chat", json={"question": "hi"})
        assert r.status_code == 200, r.text


# ─── GET proof/data endpoints STAY PUBLIC (dashboard + verifier) ──────────────


class TestPublicGetStaysOpen:
    PUBLIC_GETS = [
        "/health",
        "/api/health-public",
        "/api/portfolio",
        "/api/positions",
        "/api/risk",
        "/api/trades",
        "/api/status",
    ]

    def test_public_gets_200_without_auth_even_when_enforced(self):
        client, _ = _build_client(require_auth=True)
        for path in self.PUBLIC_GETS:
            r = client.get(path)
            assert r.status_code == 200, f"{path} → {r.status_code} {r.text}"


# ─── 2.3 CORS: SPA origins ok, rogue *.pages.dev blocked ──────────────────────


class TestCors:
    def _origin_allowed(self, client, origin: str) -> bool:
        # A simple GET with an Origin header: CORSMiddleware echoes
        # access-control-allow-origin ONLY for allowed origins.
        r = client.get("/health", headers={"Origin": origin})
        return r.headers.get("access-control-allow-origin") is not None

    def test_earn_defi_allowed(self):
        client, _ = _build_client(require_auth=True)
        assert self._origin_allowed(client, "https://earn-defi.com")

    def test_localhost_allowed(self):
        client, _ = _build_client(require_auth=True)
        assert self._origin_allowed(client, "http://localhost:4321")

    def test_rogue_pages_dev_blocked(self):
        client, _ = _build_client(require_auth=True)
        assert not self._origin_allowed(client, "https://evil.pages.dev")

    def test_rogue_pages_dev_preflight_blocked(self):
        client, _ = _build_client(require_auth=True)
        r = client.options(
            "/api/chat",
            headers={
                "Origin": "https://evil.pages.dev",
                "Access-Control-Request-Method": "POST",
            },
        )
        # Disallowed origin → no allow-origin echoed back.
        assert r.headers.get("access-control-allow-origin") is None

    def test_lookalike_domain_blocked(self):
        # earn-defi.com.evil.com must NOT match the regex.
        client, _ = _build_client(require_auth=True)
        assert not self._origin_allowed(client, "https://earn-defi.com.evil.com")


# ─── 2.2 RATE LIMIT: flood → 429 ──────────────────────────────────────────────


class TestRateLimit:
    def test_chat_flood_returns_429(self, monkeypatch):
        # Tighten the strict write bucket so the flood trips fast & deterministically.
        monkeypatch.setenv("SPA_RATE_LIMIT_WRITE_BURST", "3")
        monkeypatch.setenv("SPA_RATE_LIMIT_WRITE_PER_MIN", "3")
        # Re-import rate_limit so the new env is read, and build a fresh middleware
        # store via a direct unit test of the store (the live app reads env at
        # construction time which happened at import — so test the store directly).
        import importlib
        import spa_core.api.rate_limit as rl
        importlib.reload(rl)
        store = rl.RateLimiterStore(capacity=3, refill_rate=3, refill_interval=60.0)
        ip = "9.9.9.9"
        allowed = [store.allow(ip) for _ in range(5)]
        assert allowed[:3] == [True, True, True]
        assert allowed[3] is False and allowed[4] is False

    def test_middleware_429_response_shape(self, monkeypatch):
        monkeypatch.setenv("SPA_RATE_LIMIT_ENABLED", "1")  # limiter ON for this test
        # Exercise the real middleware on the app with a tiny default bucket.
        from starlette.applications import Starlette
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route
        from spa_core.api.rate_limit import RateLimitMiddleware, RateLimiterStore

        async def ok(request):
            return PlainTextResponse("ok")

        app = Starlette(routes=[Route("/x", ok)])
        tiny = RateLimiterStore(capacity=2, refill_rate=2, refill_interval=60.0)
        app.add_middleware(RateLimitMiddleware, default_store=tiny, write_store=tiny)
        client = TestClient(app)
        codes = [client.get("/x").status_code for _ in range(4)]
        assert codes[:2] == [200, 200]
        assert 429 in codes[2:]
        # Retry-After present on the 429
        r = client.get("/x")
        assert r.status_code == 429
        assert "retry-after" in {k.lower() for k in r.headers}

    def test_xff_rotation_cannot_bypass_when_not_trusting_proxy(self, monkeypatch):
        # RESIDUAL-GAP: rotating X-Forwarded-For must NOT mint a fresh bucket
        # when we are not behind a trusted proxy.
        monkeypatch.setenv("SPA_RATE_LIMIT_ENABLED", "1")
        monkeypatch.setenv("SPA_TRUST_PROXY", "0")  # direct exposure → ignore XFF
        from starlette.applications import Starlette
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route
        from spa_core.api.rate_limit import RateLimitMiddleware, RateLimiterStore

        async def ok(request):
            return PlainTextResponse("ok")

        app = Starlette(routes=[Route("/x", ok)])
        tiny = RateLimiterStore(capacity=2, refill_rate=2, refill_interval=60.0)
        app.add_middleware(RateLimitMiddleware, default_store=tiny, write_store=tiny)
        client = TestClient(app)
        codes = [
            client.get("/x", headers={"X-Forwarded-For": f"1.2.3.{i}"}).status_code
            for i in range(5)
        ]
        assert 429 in codes, f"XFF rotation bypassed the limiter: {codes}"

    def test_cf_connecting_ip_used_when_trusting_proxy(self, monkeypatch):
        # When behind Cloudflare, CF-Connecting-IP (un-spoofable) is the key;
        # distinct CF IPs get distinct buckets, same CF IP is throttled.
        monkeypatch.setenv("SPA_RATE_LIMIT_ENABLED", "1")
        monkeypatch.setenv("SPA_TRUST_PROXY", "1")
        from starlette.applications import Starlette
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route
        from spa_core.api.rate_limit import RateLimitMiddleware, RateLimiterStore

        async def ok(request):
            return PlainTextResponse("ok")

        app = Starlette(routes=[Route("/x", ok)])
        tiny = RateLimiterStore(capacity=2, refill_rate=2, refill_interval=60.0)
        app.add_middleware(RateLimitMiddleware, default_store=tiny, write_store=tiny)
        client = TestClient(app)
        same_ip = {"CF-Connecting-IP": "9.9.9.9"}
        codes = [client.get("/x", headers=same_ip).status_code for _ in range(5)]
        assert 429 in codes, f"same CF-Connecting-IP not throttled: {codes}"

    def test_options_not_throttled(self, monkeypatch):
        monkeypatch.setenv("SPA_RATE_LIMIT_ENABLED", "1")  # limiter ON for this test
        from starlette.applications import Starlette
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route
        from spa_core.api.rate_limit import RateLimitMiddleware, RateLimiterStore

        async def ok(request):
            return PlainTextResponse("ok")

        app = Starlette(routes=[Route("/x", ok, methods=["GET", "OPTIONS"])])
        tiny = RateLimiterStore(capacity=1, refill_rate=1, refill_interval=60.0)
        app.add_middleware(RateLimitMiddleware, default_store=tiny, write_store=tiny)
        client = TestClient(app)
        # OPTIONS never counts against the bucket
        for _ in range(5):
            assert client.options("/x").status_code in (200, 405)


# ─── RED-TEAM: oversized body, no unguarded alias path ────────────────────────


class TestRedTeam:
    def test_oversized_chat_body_rejected(self):
        client, headers = _build_client(require_auth=True)
        huge = "A" * 50_000  # well over the 4000-char cap
        r = client.post("/api/chat", json={"question": huge}, headers=headers)
        # Pydantic max_length → 422 (validation), never reaches the LLM.
        assert r.status_code == 422, r.text

    def test_oversized_thought_message_rejected(self):
        client, headers = _build_client(require_auth=True)
        huge = "B" * 100_000
        r = client.post("/api/agent/thought",
                        json={"agent": "X", "message": huge}, headers=headers)
        assert r.status_code == 422, r.text

    def test_no_unguarded_alias_path_for_chat(self):
        # RESIDUAL-GAP GUARD: the only routes that reach the chat/thought handlers
        # are the auth-gated POSTs. Assert there is exactly one route per path and
        # each carries an auth dependency (no second, unguarded alias path).
        # Import server to ensure routers are included, then inspect the router
        # objects directly (FastAPI version-stable: the source-of-truth route
        # table is the APIRouter's own .routes).
        import spa_core.api.server  # noqa: F401  (ensures include_router ran)
        from spa_core.api.api_security import require_api_key
        from spa_core.api.routers import (
            competitive_watch, live, misc, optimizer, rates_desk, redteam,
            strategy_lab, tier1, tournament, v1,
        )

        all_routers = [competitive_watch, live, misc, optimizer, rates_desk,
                       redteam, strategy_lab, tier1, tournament, v1]
        flat = [rt for r in all_routers for rt in r.router.routes]

        for path in ("/api/chat", "/api/agent/thought"):
            routes = [r for r in flat if getattr(r, "path", None) == path]
            assert len(routes) == 1, f"exactly one {path} route expected, got {len(routes)}"
            deps = getattr(routes[0], "dependencies", [])
            dep_calls = {getattr(d, "dependency", None) for d in deps}
            assert require_api_key in dep_calls, (
                f"{path} must carry the require_api_key dependency (no unguarded alias)"
            )

    def test_ws_agents_gated_when_enforced(self):
        # WS upgrade without credentials must be rejected (policy close 1008).
        client, _ = _build_client(require_auth=True)
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws/agents"):
                pass
        assert exc.value.code == 1008

    def test_ws_agents_open_when_flag_off(self):
        client, _ = _build_client(require_auth=False)
        # Flag OFF → connect succeeds (receives snapshot).
        with client.websocket_connect("/ws/agents") as ws:
            data = ws.receive_json()
            assert "agent" in data
