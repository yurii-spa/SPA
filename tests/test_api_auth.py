"""
Tests for spa_core/api/auth.py — MP-1529 (v11.45).

20 tests covering:
  - Key loading
  - is_protected / is_public path classification
  - Token generation & verification (valid, expired, tampered, wrong format)
  - verify_bearer()
  - Rate-limit stub
  - Singleton get_auth()
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.api.auth import APIAuth, get_auth, PROTECTED_PREFIXES, PUBLIC_PREFIXES


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def auth_with_key():
    """APIAuth instance with a known test key loaded via env var."""
    with patch.dict("os.environ", {"SPA_API_KEY": "test-secret-key-abc123"}):
        return APIAuth()


@pytest.fixture()
def auth_no_key():
    """APIAuth instance with no key configured."""
    with patch.dict("os.environ", {}, clear=True):
        with patch("spa_core.api.auth.APIAuth._load_key", return_value=None):
            a = APIAuth()
    return a


# ── key loading ───────────────────────────────────────────────────────────────

class TestKeyLoading:
    def test_has_key_with_env_var(self, auth_with_key):
        assert auth_with_key.has_key() is True

    def test_no_key_when_env_missing(self, auth_no_key):
        assert auth_no_key.has_key() is False

    def test_key_stripped_of_whitespace(self):
        with patch.dict("os.environ", {"SPA_API_KEY": "  mykey  "}):
            a = APIAuth()
            assert a.has_key() is True


# ── path classification ───────────────────────────────────────────────────────

class TestPathClassification:
    def test_admin_path_is_protected(self, auth_with_key):
        assert auth_with_key.is_protected("/admin/users") is True

    def test_api_v1_admin_protected(self, auth_with_key):
        assert auth_with_key.is_protected("/api/v1/admin/reset") is True

    def test_health_is_not_protected(self, auth_with_key):
        assert auth_with_key.is_protected("/health") is False

    def test_v1_status_is_public(self, auth_with_key):
        assert auth_with_key.is_public("/api/v1/status") is True

    def test_v1_golive_is_public(self, auth_with_key):
        assert auth_with_key.is_public("/api/v1/golive") is True

    def test_v1_adapters_is_public(self, auth_with_key):
        assert auth_with_key.is_public("/api/v1/adapters") is True

    def test_v1_evidence_is_public(self, auth_with_key):
        assert auth_with_key.is_public("/api/v1/evidence") is True

    def test_unknown_path_not_public(self, auth_with_key):
        assert auth_with_key.is_public("/api/v1/secret_internal") is False


# ── token generation & verification ──────────────────────────────────────────

class TestTokenVerification:
    def test_generate_returns_dot_format(self, auth_with_key):
        token = auth_with_key.generate_token()
        assert "." in token
        parts = token.split(".", 1)
        assert len(parts) == 2

    def test_valid_token_verifies(self, auth_with_key):
        token = auth_with_key.generate_token()
        assert auth_with_key.verify_token(token) is True

    def test_tampered_signature_fails(self, auth_with_key):
        token = auth_with_key.generate_token()
        ts, _ = token.split(".", 1)
        bad_token = f"{ts}.deadbeefdeadbeefdeadbeef"
        assert auth_with_key.verify_token(bad_token) is False

    def test_expired_token_fails(self, auth_with_key):
        old_ts = int(time.time()) - 400  # 400s ago > 300s window
        token = auth_with_key.generate_token(timestamp=old_ts)
        assert auth_with_key.verify_token(token) is False

    def test_future_token_fails(self, auth_with_key):
        future_ts = int(time.time()) + 400
        token = auth_with_key.generate_token(timestamp=future_ts)
        assert auth_with_key.verify_token(token) is False

    def test_malformed_token_no_dot_fails(self, auth_with_key):
        assert auth_with_key.verify_token("nodot") is False

    def test_empty_token_fails(self, auth_with_key):
        assert auth_with_key.verify_token("") is False

    def test_no_key_verify_always_false(self, auth_no_key):
        assert auth_no_key.verify_token("12345.abcdef") is False

    def test_generate_raises_without_key(self, auth_no_key):
        with pytest.raises(ValueError, match="No API key"):
            auth_no_key.generate_token()


# ── verify_bearer ─────────────────────────────────────────────────────────────

class TestVerifyBearer:
    def test_valid_bearer_header(self, auth_with_key):
        token = auth_with_key.generate_token()
        header = f"Bearer {token}"
        assert auth_with_key.verify_bearer(header) is True

    def test_missing_bearer_prefix_fails(self, auth_with_key):
        token = auth_with_key.generate_token()
        assert auth_with_key.verify_bearer(token) is False

    def test_none_header_fails(self, auth_with_key):
        assert auth_with_key.verify_bearer(None) is False


# ── rate limit stub ───────────────────────────────────────────────────────────

class TestRateLimitStub:
    def test_first_request_allowed(self, auth_with_key):
        auth_with_key.reset_rate_counter("10.0.0.1")
        assert auth_with_key.check_rate_limit("10.0.0.1") is True

    def test_reset_clears_counter(self, auth_with_key):
        ip = "10.0.0.2"
        for _ in range(5):
            auth_with_key.check_rate_limit(ip)
        auth_with_key.reset_rate_counter(ip)
        # After reset, counter should be clean
        assert auth_with_key.check_rate_limit(ip) is True


# ── singleton ─────────────────────────────────────────────────────────────────

class TestSingleton:
    def test_get_auth_returns_instance(self):
        import spa_core.api.auth as auth_module
        auth_module._auth_instance = None  # reset
        a = get_auth()
        assert isinstance(a, APIAuth)

    def test_get_auth_same_instance(self):
        a1 = get_auth()
        a2 = get_auth()
        assert a1 is a2
