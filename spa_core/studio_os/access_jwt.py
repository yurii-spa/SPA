"""spa_core/studio_os/access_jwt.py — Cloudflare Access JWT verification (ADR-552, stdlib only).

Mission Control's only owner-exposed public path (``MC_PUBLIC_HOST``) sits behind Cloudflare
Access. Every such request carries a ``Cf-Access-Jwt-Assertion`` header: a JWT signed by
Cloudflare's team key, RS256. This module verifies that token WITHOUT any third-party crypto
library (invariant #4 — only stdlib in runtime): RSA signature verification is ``pow(sig, e, n)``
compared against the EMSA-PKCS1-v1_5 encoding of the SHA-256 digest, exactly as RFC 3447 defines it.

Fail-CLOSED throughout: every rejection raises :class:`AccessDenied` with a human-readable reason
(never silently returns something false-y) and the caller (``mission_server.py``) turns ANY
raised reason into the same 403 — the reason is for logs/tests, never for the client.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
import urllib.request
from typing import Any, Callable, Optional

#: DER prefix of DigestInfo for id-sha256 (RFC 3447 §9.2 note 1) — precedes the raw 32-byte
#: digest inside an EMSA-PKCS1-v1_5 encoded message.
_SHA256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")

#: Allowed clock skew for nbf/iat (ahead-of-now tolerance only; exp is checked strictly > now).
CLOCK_SKEW_S = 60


class AccessDenied(Exception):
    """Raised with a human-readable reason. Never carries the token itself."""


# ── base64url helpers ────────────────────────────────────────────────────────────────────────────
def _b64url_decode(s: str) -> bytes:
    s = (s or "").strip()
    pad = "=" * (-len(s) % 4)
    try:
        return base64.urlsafe_b64decode(s + pad)
    except (ValueError, TypeError) as exc:
        raise AccessDenied(f"malformed base64url: {exc}") from exc


def _b64url_decode_int(s: str) -> int:
    return int.from_bytes(_b64url_decode(s), "big")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


# ── RSA / RS256 (RFC 3447, stdlib-only) ─────────────────────────────────────────────────────────
def _emsa_pkcs1_v15_encode(digest: bytes, modulus_len_bytes: int) -> bytes:
    """RFC 3447 §9.2 EMSA-PKCS1-v1_5-ENCODE, specialised to SHA-256."""
    t = _SHA256_DIGEST_INFO_PREFIX + digest
    if modulus_len_bytes < len(t) + 11:
        raise AccessDenied("RSA modulus too short for a SHA-256 PKCS#1 v1.5 signature")
    ps_len = modulus_len_bytes - len(t) - 3
    return b"\x00\x01" + (b"\xff" * ps_len) + b"\x00" + t


def _jwk_to_rsa_public(jwk: dict) -> tuple:
    n_b64, e_b64 = jwk.get("n"), jwk.get("e")
    if not n_b64 or not e_b64:
        raise AccessDenied("JWK is missing n/e")
    return _b64url_decode_int(n_b64), _b64url_decode_int(e_b64)


def _find_key(certs: dict, kid: str) -> dict:
    for k in (certs or {}).get("keys") or []:
        if k.get("kid") == kid:
            return k
    raise AccessDenied(f"unknown kid: {kid!r}")


def _rs256_verify(signing_input: bytes, signature: bytes, n: int, e: int) -> bool:
    modulus_len = (n.bit_length() + 7) // 8
    if len(signature) != modulus_len:
        return False
    sig_int = int.from_bytes(signature, "big")
    if sig_int >= n:
        return False
    digest = hashlib.sha256(signing_input).digest()
    expected = _emsa_pkcs1_v15_encode(digest, modulus_len)
    actual = pow(sig_int, e, n).to_bytes(modulus_len, "big")
    return hmac.compare_digest(actual, expected)  # constant-time


# ── public API ──────────────────────────────────────────────────────────────────────────────────
def verify(token: str, *, certs: dict, audience: str, issuer: str,
           allowed_emails: Any, now: float) -> dict:
    """Verify a Cloudflare Access RS256 JWT. Returns the claims dict, or raises ``AccessDenied``.

    Checks, in order: JWT shape → ``alg``/``kid`` → RSA signature → ``exp`` → ``nbf``/``iat``
    (± :data:`CLOCK_SKEW_S`) → ``aud`` → ``iss`` → ``email`` (case-insensitive membership of
    ``allowed_emails``).
    """
    if not token or not isinstance(token, str):
        raise AccessDenied("empty or non-string token")
    if not token.isascii():
        # Finding #14: reject non-ASCII tokens up front rather than let a decode step downstream
        # discover it indirectly. A base64url/JWT token is ASCII by construction; anything else
        # did not come from Cloudflare Access.
        raise AccessDenied("token is not ASCII")
    parts = token.split(".")
    if len(parts) != 3:
        raise AccessDenied("not a JWT (expected header.payload.signature)")
    header_b64, payload_b64, sig_b64 = parts

    try:
        header = json.loads(_b64url_decode(header_b64))
    except (ValueError, TypeError) as exc:
        raise AccessDenied(f"malformed header: {exc}") from exc
    if not isinstance(header, dict):
        raise AccessDenied("header is not an object")
    if header.get("alg") != "RS256":
        raise AccessDenied(f"unsupported alg: {header.get('alg')!r}")
    kid = header.get("kid")
    if not kid:
        raise AccessDenied("header missing kid")

    jwk = _find_key(certs, kid)
    n, e = _jwk_to_rsa_public(jwk)
    try:
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    except (ValueError, UnicodeError) as exc:
        raise AccessDenied(f"signing input not ASCII: {exc}") from exc
    try:
        signature = _b64url_decode(sig_b64)
    except AccessDenied:
        raise
    if not _rs256_verify(signing_input, signature, n, e):
        raise AccessDenied("signature verification failed")

    try:
        claims = json.loads(_b64url_decode(payload_b64))
    except (ValueError, TypeError) as exc:
        raise AccessDenied(f"malformed payload: {exc}") from exc
    if not isinstance(claims, dict):
        raise AccessDenied("payload is not an object")

    exp = claims.get("exp")
    if exp is None:
        raise AccessDenied("missing exp")
    try:
        if not (float(exp) > now):
            raise AccessDenied("token expired")
    except (TypeError, ValueError) as exc:
        raise AccessDenied(f"malformed exp: {exc}") from exc

    for field in ("nbf", "iat"):
        v = claims.get(field)
        if v is None:
            continue
        try:
            if float(v) > now + CLOCK_SKEW_S:
                raise AccessDenied(f"token not yet valid ({field} in the future)")
        except (TypeError, ValueError) as exc:
            raise AccessDenied(f"malformed {field}: {exc}") from exc

    aud = claims.get("aud")
    aud_list = aud if isinstance(aud, list) else ([aud] if aud is not None else [])
    if audience not in aud_list:
        raise AccessDenied("aud mismatch")

    if claims.get("iss") != issuer:
        raise AccessDenied("iss mismatch")

    allowed_lower = {str(x).strip().lower() for x in (allowed_emails or ())}
    email = str(claims.get("email") or "").strip().lower()
    if not email or email not in allowed_lower:
        raise AccessDenied("email not allowed")

    return claims


def peek_kid(token: Any) -> Optional[str]:
    """Best-effort peek at a JWT's header ``kid``, for cache-refresh hints ONLY. Never raises —
    anything that does not look like a well-formed JWT header returns ``None``. This is never the
    security check: :func:`verify` re-validates everything (signature, claims) regardless of what
    this returns, so a caller cannot gain anything by lying to this function.
    """
    try:
        if not isinstance(token, str) or not token or not token.isascii():
            return None
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header = json.loads(_b64url_decode(parts[0]))
        if not isinstance(header, dict):
            return None
        kid = header.get("kid")
        return kid if isinstance(kid, str) else None
    except Exception:  # noqa: BLE001 — a hint function must never raise
        return None


class CertsCache:
    """In-memory TTL cache around :func:`fetch_certs` (finding #3). NO disk cache (finding #4,
    second review round): a disk cache is one more thing to trust (mode, ownership, a
    ``fetched_at`` that is just a JSON field an attacker with write access could set to the
    future to pin a cert set forever) for a benefit — surviving a brief Cloudflare outage — that
    is not worth that surface. Past TTL with the endpoint down, this fails CLOSED: deny, don't
    serve stale keys.

    Without this, every request re-fetched the Access certs over the network. One instance is
    created per :class:`mission_server.AccessConfig` (per server lifetime, not per request), so a
    steady request stream makes one network fetch per ``ttl_s`` instead of one per request.

    A request bearing a ``kid`` that is not among the cached keys triggers at most ONE opportunistic
    refetch per ``kid_retry_s`` seconds (key rotation can add a kid between TTL ticks); beyond that
    throttle an unknown kid is just denied without hammering the network.

    A FAILED fetch is throttled the same way (finding #5): after a failure, further requests are
    denied without re-attempting the network call for ``failure_retry_s`` seconds — otherwise an
    outage turns every single request into an outbound HTTP call that will also fail.

    Thread-safe: multiple request-handling threads share one instance.
    """

    def __init__(self, team_domain: str, ttl_s: int = 3600, kid_retry_s: float = 60.0,
                 failure_retry_s: float = 30.0, opener: Optional[Callable] = None):
        self.team_domain = team_domain
        self.ttl_s = ttl_s
        self.kid_retry_s = kid_retry_s
        self.failure_retry_s = failure_retry_s
        self.opener = opener
        self._certs: Optional[dict] = None
        self._fetched_at: float = 0.0
        self._last_kid_retry: float = 0.0
        self._last_failure_at: float = 0.0
        self._last_failure_reason: Optional[str] = None
        self._lock = threading.Lock()

    def _known_kid(self, kid: str) -> bool:
        return any(k.get("kid") == kid for k in (self._certs or {}).get("keys") or [])

    def get(self, kid: Optional[str] = None, now: Optional[float] = None) -> dict:
        """Return the cached certs, fetching only when stale or (throttled) when ``kid`` is
        unknown. Raises :class:`AccessDenied` exactly as :func:`fetch_certs` would — including
        when a PRIOR fetch failed recently and the throttle denies without retrying."""
        now = time.time() if now is None else now
        with self._lock:
            stale = self._certs is None or (now - self._fetched_at) > self.ttl_s
            retry_unknown_kid = (
                not stale and kid is not None and not self._known_kid(kid)
                and (now - self._last_kid_retry) >= self.kid_retry_s
            )
            if stale or retry_unknown_kid:
                if (self._last_failure_at
                        and (now - self._last_failure_at) < self.failure_retry_s):
                    raise AccessDenied(
                        f"certs endpoint failed recently ({self._last_failure_reason}); "
                        f"retry throttled for {self.failure_retry_s - (now - self._last_failure_at):.0f}s more"
                    )
                if retry_unknown_kid:
                    self._last_kid_retry = now
                try:
                    self._certs = fetch_certs(self.team_domain, ttl_s=self.ttl_s,
                                               opener=self.opener)
                except AccessDenied as exc:
                    self._last_failure_at = now
                    self._last_failure_reason = str(exc)
                    raise
                self._fetched_at = now
                self._last_failure_at = 0.0
                self._last_failure_reason = None
            return self._certs


def fetch_certs(team_domain: str, ttl_s: int = 3600, opener: Optional[Callable] = None) -> dict:
    """Fetch ``https://<team_domain>/cdn-cgi/access/certs``. NO disk cache (finding #4) — any
    fetch/parse failure raises :class:`AccessDenied` directly: an unreachable Access gate must
    fail closed, never silently accept everyone, and never serve keys nobody re-checked.

    ``opener`` is injectable (tests never touch the network): a callable
    ``opener(urllib.request.Request, timeout=...) -> response`` with ``response.read()``.
    Defaults to :func:`urllib.request.urlopen`.
    """
    opener = opener or urllib.request.urlopen
    url = f"https://{team_domain}/cdn-cgi/access/certs"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with opener(req, timeout=10) as resp:
            raw = resp.read()
        certs = json.loads(raw.decode("utf-8"))
        if not isinstance(certs, dict) or not isinstance(certs.get("keys"), list):
            raise ValueError("unexpected certs payload shape (no 'keys' list)")
    except Exception as exc:  # noqa: BLE001 — any network/parse failure is fail-CLOSED
        raise AccessDenied(f"Access certs unreachable: {type(exc).__name__}: {exc}") from exc
    return certs
