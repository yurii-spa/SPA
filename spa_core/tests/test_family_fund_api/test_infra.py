"""Тесты инфраструктуры: rate limiter, file_store, keychain, models, CORS."""
from __future__ import annotations

import os
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from spa_core.family_fund.api import file_store, keychain
from spa_core.family_fund.api.models import (
    ROLE_HIERARCHY,
    PositionItem,
    UserRole,
    YieldDayItem,
)
from spa_core.family_fund.api.rate_limiter import RateLimiterStore, TokenBucket

from .conftest import auth_header


# ── TokenBucket ───────────────────────────────────────────────────────────────
class TestTokenBucket:
    def test_allows_up_to_capacity(self):
        b = TokenBucket(capacity=3, refill_rate=3, refill_interval=60.0)
        assert b.allow() and b.allow() and b.allow()
        assert not b.allow()

    def test_remaining_decrements(self):
        b = TokenBucket(capacity=5, refill_rate=5, refill_interval=60.0)
        b.allow()
        assert b.remaining == 4

    def test_reset_after_positive_when_drained(self):
        b = TokenBucket(capacity=1, refill_rate=1, refill_interval=60.0)
        b.allow()
        assert b.reset_after > 0

    def test_refill_restores_tokens(self):
        b = TokenBucket(capacity=2, refill_rate=2, refill_interval=0.01)
        b.allow()
        b.allow()
        import time

        time.sleep(0.02)
        assert b.allow()

    def test_cost_greater_than_one(self):
        b = TokenBucket(capacity=5, refill_rate=5, refill_interval=60.0)
        assert b.allow(cost=5)
        assert not b.allow(cost=1)


class TestRateLimiterStore:
    def test_separate_keys_independent(self):
        s = RateLimiterStore(capacity=1, refill_rate=1, refill_interval=60.0)
        assert s.allow("ip1")
        assert s.allow("ip2")
        assert not s.allow("ip1")

    def test_get_bucket_stable(self):
        s = RateLimiterStore(capacity=2, refill_rate=2, refill_interval=60.0)
        assert s.get_bucket("k") is s.get_bucket("k")

    def test_reset_clears(self):
        s = RateLimiterStore(capacity=1, refill_rate=1, refill_interval=60.0)
        s.allow("k")
        s.reset()
        assert s.allow("k")

    def test_cleanup_removes_full(self):
        s = RateLimiterStore(capacity=2, refill_rate=2, refill_interval=60.0)
        s.get_bucket("idle")
        s.cleanup()
        # после cleanup новый бакет создаётся заново (полный)
        assert s.get_bucket("idle").remaining == 2


# ── file_store ────────────────────────────────────────────────────────────────
class TestFileStore:
    def test_path_traversal_blocked(self):
        with pytest.raises(ValueError):
            file_store._allowed_path("../../etc/passwd")

    def test_path_traversal_absolute_blocked(self):
        with pytest.raises(ValueError):
            file_store._allowed_path("/etc/passwd")

    def test_data_prefix_accepted(self, data_dir):
        # 'data/foo.json' и 'foo.json' резолвятся одинаково
        a = file_store._allowed_path("data/current_positions.json")
        b = file_store._allowed_path("current_positions.json")
        assert a == b

    def test_missing_file_returns_empty(self, data_dir):
        assert file_store.read_json_sync("does_not_exist.json") == {}

    def test_read_existing(self, data_dir):
        d = file_store.read_json_sync("current_positions.json")
        assert d["capital_usd"] == 100000.0

    def test_list_data_files(self, data_dir):
        files = file_store.list_data_files("daily_report_*.json")
        assert "daily_report_2026-06-18.json" in files
        assert files == sorted(files)

    def test_list_rejects_path(self, data_dir):
        with pytest.raises(ValueError):
            file_store.list_data_files("../*.json")

    def test_cache_used(self, data_dir):
        file_store.invalidate_cache()
        first = file_store.read_json_sync("current_positions.json")
        # перезаписываем файл; из-за TTL-кэша должны увидеть старое
        (data_dir / "current_positions.json").write_text("{}", encoding="utf-8")
        second = file_store.read_json_sync("current_positions.json")
        assert first == second


# ── keychain ──────────────────────────────────────────────────────────────────
class TestKeychain:
    def test_env_fallback(self, monkeypatch):
        keychain.reset_cache()
        monkeypatch.setattr(keychain, "_read_from_keychain", lambda s: None)
        monkeypatch.setenv("FAMILY_FUND_JWT_SECRET", "x" * 40)
        assert keychain.get_jwt_secret() == "x" * 40
        keychain.reset_cache()

    def test_short_secret_rejected(self, monkeypatch):
        keychain.reset_cache()
        monkeypatch.setattr(keychain, "_read_from_keychain", lambda s: None)
        monkeypatch.setenv("FAMILY_FUND_JWT_SECRET", "short")
        with pytest.raises(ValueError):
            keychain.get_jwt_secret()
        keychain.reset_cache()

    def test_missing_secret_raises(self, monkeypatch):
        keychain.reset_cache()
        monkeypatch.setattr(keychain, "_read_from_keychain", lambda s: None)
        monkeypatch.delenv("FAMILY_FUND_JWT_SECRET", raising=False)
        with pytest.raises(RuntimeError):
            keychain.get_jwt_secret()
        keychain.reset_cache()
        os.environ.setdefault(
            "FAMILY_FUND_JWT_SECRET",
            "test-secret-family-fund-32-characters-minimum!!",
        )


# ── models ────────────────────────────────────────────────────────────────────
class TestModels:
    def test_role_hierarchy_order(self):
        assert (
            ROLE_HIERARCHY[UserRole.OWNER]
            > ROLE_HIERARCHY[UserRole.ADMIN]
            > ROLE_HIERARCHY[UserRole.INVESTOR]
            > ROLE_HIERARCHY[UserRole.READONLY]
        )

    def test_position_item_decimal_coercion(self):
        p = PositionItem(protocol="aave_v3", allocation_usd="100.5", weight_pct="10")
        assert p.allocation_usd == Decimal("100.5")
        assert isinstance(p.allocation_usd, Decimal)

    def test_position_negative_rejected(self):
        with pytest.raises(Exception):
            PositionItem(protocol="x", allocation_usd="-1", weight_pct="10")

    def test_yield_day_bad_date_rejected(self):
        with pytest.raises(Exception):
            YieldDayItem(date="bad", equity_usd="1")

    def test_yield_day_optional_none(self):
        d = YieldDayItem(date="2026-06-18", equity_usd="100")
        assert d.daily_yield_usd is None


# ── CORS ──────────────────────────────────────────────────────────────────────
class TestCORS:
    def test_cors_allows_known_origin(self, client: TestClient):
        r = client.get("/health", headers={"Origin": "https://earn-defi.com"})
        assert r.headers.get("access-control-allow-origin") == "https://earn-defi.com"

    def test_cors_localhost_dev(self, client: TestClient):
        r = client.get("/health", headers={"Origin": "http://localhost:5173"})
        assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_cors_credentials_allowed(self, client: TestClient):
        r = client.get("/health", headers={"Origin": "https://earn-defi.com"})
        assert r.headers.get("access-control-allow-credentials") == "true"


# ── Error format ──────────────────────────────────────────────────────────────
class TestErrorFormat:
    def test_401_has_error_envelope(self, client: TestClient):
        r = client.get("/portfolio")
        body = r.json()
        assert "error" in body
        assert body["error"]["code"] == "http_error"

    def test_422_has_errors_list(self, client: TestClient, investor_token):
        r = client.get(
            "/yield/history?days=0", headers=auth_header(investor_token)
        )
        body = r.json()
        assert body["error"]["code"] == "validation_error"
        assert "errors" in body
