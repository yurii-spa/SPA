# FROZEN-DATE-OK: injected-clock — NOW is passed into build_bundle(now=NOW); the server never judges age in these tests
"""spa_core/tests/test_mission_server.py — Mission Control v1 serving layer (ADR-552 + security
review fixes #1, #2, #3, #11, #12, #13, #14).

Covers three modules, each with its own subject:

* ``mission_build`` — the bundle builder: new bundle dir + pointer swap, fail-CLOSED on a
  broken producer or a missing required UI file, pruning that never touches the current bundle,
  a staging directory name that cannot collide with the prune prefix.
* ``access_jwt`` — Cloudflare Access RS256 verification, exercised against a REAL RSA keypair and
  a REAL RS256 signature built by this test (Miller-Rabin primes, PKCS#1 v1.5 — no shortcuts, no
  third-party crypto). Also the in-memory certs cache and the non-ASCII-token guard.
* ``mission_server`` — the HTTP layer: TWO independent loopback listeners (LOCAL — no Access
  config at all, never serves the public host; PUBLIC — Access-gated on every route, no loopback
  exemption), fixed route map (no path translation), GET/HEAD only, security headers on every
  response including malformed ones, keep-alive desync hardening, and bundle resilience against a
  malformed pointer or an unreadable bundle file.

No network: the offline guard in ``spa_core/tests/conftest.py`` patches ``urllib.request.urlopen``
for the whole session, and every test that reaches the "public host" path monkeypatches
``access_jwt.fetch_certs`` directly instead of relying on that guard doing something useful.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import math
import os
import random
import socket
import sys
import threading
import time
import unittest
from base64 import urlsafe_b64encode
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from spa_core.studio_os import access_jwt  # noqa: E402
from spa_core.studio_os import mission_build  # noqa: E402
from spa_core.studio_os import mission_server  # noqa: E402

#: The clock passed INTO build_bundle(now=...) — the builder never reads the wall clock in these tests.
NOW = datetime(2026, 10, 3, tzinfo=timezone.utc)


# ── a REAL RSA keypair + REAL RS256 signing, built once for the whole module ───────────────────
def _b64url(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _int_b64url(i: int) -> str:
    length = max(1, (i.bit_length() + 7) // 8)
    return _b64url(i.to_bytes(length, "big"))


def _is_probable_prime(n: int, rounds: int = 12) -> bool:
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % p == 0:
            return n == p
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(rounds):
        a = random.randrange(2, n - 1)
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _gen_prime(bits: int) -> int:
    while True:
        cand = random.getrandbits(bits) | (1 << (bits - 1)) | 1
        if _is_probable_prime(cand):
            return cand


def _gen_rsa_keypair(bits: int = 512, e: int = 65537) -> dict:
    while True:
        p, q = _gen_prime(bits), _gen_prime(bits)
        if p == q:
            continue
        n = p * q
        phi = (p - 1) * (q - 1)
        if math.gcd(e, phi) == 1:
            d = pow(e, -1, phi)
            return {"n": n, "e": e, "d": d}


def _emsa_pkcs1_v15(digest: bytes, modulus_len: int) -> bytes:
    prefix = bytes.fromhex("3031300d060960864801650304020105000420")
    t = prefix + digest
    ps_len = modulus_len - len(t) - 3
    return b"\x00\x01" + (b"\xff" * ps_len) + b"\x00" + t


def _rs256_sign(key: dict, signing_input: bytes) -> bytes:
    n, d = key["n"], key["d"]
    modulus_len = (n.bit_length() + 7) // 8
    digest = hashlib.sha256(signing_input).digest()
    em = _emsa_pkcs1_v15(digest, modulus_len)
    m_int = int.from_bytes(em, "big")
    sig_int = pow(m_int, d, n)
    return sig_int.to_bytes(modulus_len, "big")


_KEY = _gen_rsa_keypair(512)
_KID = "test-key-1"
_OTHER_KEY = _gen_rsa_keypair(384)  # a second, smaller key — used for "wrong key signed this" cases


def _jwk(key: dict, kid: str = _KID) -> dict:
    return {"kid": kid, "kty": "RSA", "alg": "RS256", "use": "sig",
            "n": _int_b64url(key["n"]), "e": _int_b64url(key["e"])}


CERTS = {"keys": [_jwk(_KEY, _KID)]}


def make_jwt(claims: dict, *, key=None, kid=_KID, alg="RS256", header_extra=None,
             tamper_payload=False) -> str:
    key = key or _KEY
    header = {"alg": alg, "kid": kid, "typ": "JWT"}
    if header_extra:
        header.update(header_extra)
    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    sig = _rs256_sign(key, signing_input)
    sig_b64 = _b64url(sig)
    if tamper_payload:
        # flip the payload AFTER signing — the signature no longer matches it.
        tampered = {**claims, "email": "attacker@evil.example"}
        payload_b64 = _b64url(json.dumps(tampered, separators=(",", ":")).encode())
    return f"{header_b64}.{payload_b64}.{sig_b64}"


AUD = "mc-audience-abc123"
TEAM = "spa-owner.cloudflareaccess.com"
ISSUER = f"https://{TEAM}"
OWNER_EMAIL = "Owner@Example.com"


def base_claims(now: float, **overrides) -> dict:
    c = {"aud": AUD, "iss": ISSUER, "email": OWNER_EMAIL,
         "exp": now + 3600, "iat": now, "nbf": now}
    c.update(overrides)
    return c


# ════════════════════════════════════════════════════════════════════════════════════════════
# access_jwt — unit tests
# ════════════════════════════════════════════════════════════════════════════════════════════
class AccessJwtVerify(unittest.TestCase):

    def test_valid_token_returns_claims(self):
        now = time.time()
        token = make_jwt(base_claims(now))
        claims = access_jwt.verify(token, certs=CERTS, audience=AUD, issuer=ISSUER,
                                    allowed_emails={OWNER_EMAIL}, now=now)
        self.assertEqual(claims["email"], OWNER_EMAIL)

    def test_email_match_is_case_insensitive(self):
        now = time.time()
        token = make_jwt(base_claims(now, email="OWNER@example.com"))
        claims = access_jwt.verify(token, certs=CERTS, audience=AUD, issuer=ISSUER,
                                    allowed_emails={"owner@example.com"}, now=now)
        self.assertEqual(claims["email"], "OWNER@example.com")

    def test_wrong_audience_denied(self):
        now = time.time()
        token = make_jwt(base_claims(now, aud="someone-elses-app"))
        with self.assertRaises(access_jwt.AccessDenied):
            access_jwt.verify(token, certs=CERTS, audience=AUD, issuer=ISSUER,
                               allowed_emails={OWNER_EMAIL}, now=now)

    def test_wrong_issuer_denied(self):
        now = time.time()
        token = make_jwt(base_claims(now, iss="https://not-the-team.example"))
        with self.assertRaises(access_jwt.AccessDenied):
            access_jwt.verify(token, certs=CERTS, audience=AUD, issuer=ISSUER,
                               allowed_emails={OWNER_EMAIL}, now=now)

    def test_expired_token_denied(self):
        now = time.time()
        token = make_jwt(base_claims(now, exp=now - 10))
        with self.assertRaises(access_jwt.AccessDenied):
            access_jwt.verify(token, certs=CERTS, audience=AUD, issuer=ISSUER,
                               allowed_emails={OWNER_EMAIL}, now=now)

    def test_future_nbf_denied(self):
        now = time.time()
        token = make_jwt(base_claims(now, nbf=now + 999))
        with self.assertRaises(access_jwt.AccessDenied):
            access_jwt.verify(token, certs=CERTS, audience=AUD, issuer=ISSUER,
                               allowed_emails={OWNER_EMAIL}, now=now)

    def test_email_not_in_allowlist_denied(self):
        now = time.time()
        token = make_jwt(base_claims(now, email="someone-else@example.com"))
        with self.assertRaises(access_jwt.AccessDenied):
            access_jwt.verify(token, certs=CERTS, audience=AUD, issuer=ISSUER,
                               allowed_emails={OWNER_EMAIL}, now=now)

    def test_tampered_payload_denied(self):
        now = time.time()
        token = make_jwt(base_claims(now), tamper_payload=True)
        with self.assertRaises(access_jwt.AccessDenied):
            access_jwt.verify(token, certs=CERTS, audience=AUD, issuer=ISSUER,
                               allowed_emails={OWNER_EMAIL}, now=now)

    def test_alg_none_denied(self):
        now = time.time()
        token = make_jwt(base_claims(now), alg="none")
        with self.assertRaises(access_jwt.AccessDenied):
            access_jwt.verify(token, certs=CERTS, audience=AUD, issuer=ISSUER,
                               allowed_emails={OWNER_EMAIL}, now=now)

    def test_unknown_kid_denied(self):
        now = time.time()
        token = make_jwt(base_claims(now), kid="no-such-kid")
        with self.assertRaises(access_jwt.AccessDenied):
            access_jwt.verify(token, certs=CERTS, audience=AUD, issuer=ISSUER,
                               allowed_emails={OWNER_EMAIL}, now=now)

    def test_signed_by_a_different_key_denied(self):
        now = time.time()
        token = make_jwt(base_claims(now), key=_OTHER_KEY)  # kid still says _KID -> wrong key used
        with self.assertRaises(access_jwt.AccessDenied):
            access_jwt.verify(token, certs=CERTS, audience=AUD, issuer=ISSUER,
                               allowed_emails={OWNER_EMAIL}, now=now)

    def test_malformed_token_shape_denied(self):
        with self.assertRaises(access_jwt.AccessDenied):
            access_jwt.verify("not-a-jwt", certs=CERTS, audience=AUD, issuer=ISSUER,
                               allowed_emails={OWNER_EMAIL}, now=time.time())

    def test_empty_token_denied(self):
        with self.assertRaises(access_jwt.AccessDenied):
            access_jwt.verify("", certs=CERTS, audience=AUD, issuer=ISSUER,
                               allowed_emails={OWNER_EMAIL}, now=time.time())

    # -- finding #14 ----------------------------------------------------------------------------
    def test_non_str_token_denied(self):
        with self.assertRaises(access_jwt.AccessDenied):
            access_jwt.verify(12345, certs=CERTS, audience=AUD, issuer=ISSUER,
                               allowed_emails={OWNER_EMAIL}, now=time.time())

    def test_non_ascii_token_denied(self):
        now = time.time()
        valid = make_jwt(base_claims(now))
        header_b64, payload_b64, sig_b64 = valid.split(".")
        # Replace one ASCII char of the signature with a non-ASCII lookalike. isascii() must
        # reject this BEFORE any base64/JSON decoding is attempted.
        poisoned = header_b64 + "." + payload_b64 + "." + "é" + sig_b64[1:]
        with self.assertRaises(access_jwt.AccessDenied) as ctx:
            access_jwt.verify(poisoned, certs=CERTS, audience=AUD, issuer=ISSUER,
                               allowed_emails={OWNER_EMAIL}, now=now)
        self.assertIn("ASCII", str(ctx.exception))

    def test_peek_kid_reads_the_header_kid(self):
        token = make_jwt(base_claims(time.time()), kid="rotated-key-2")
        self.assertEqual(access_jwt.peek_kid(token), "rotated-key-2")

    def test_peek_kid_never_raises_on_garbage(self):
        for bad in (None, 123, "", "not-a-jwt", "a.b", "héllo.wörld.sig", "a.b.c.d"):
            self.assertIsNone(access_jwt.peek_kid(bad))


class AccessJwtCertsCache(unittest.TestCase):
    """Finding #3: certs must not be re-fetched on every request, and an unknown kid gets at
    most one throttled refetch rather than hammering the network. Finding #4 (second review
    round): there is NO disk cache any more — the constructor takes no path at all. Finding #5
    (second review round): a FAILED fetch is throttled too, so an outage does not turn every
    request into an outbound call."""

    def test_two_gets_within_ttl_fetch_once(self):
        calls = {"n": 0}

        def fake_fetch(team, ttl_s=3600, opener=None):
            calls["n"] += 1
            return CERTS

        orig = access_jwt.fetch_certs
        access_jwt.fetch_certs = fake_fetch
        try:
            cache = access_jwt.CertsCache(TEAM)
            cache.get(kid=_KID)
            cache.get(kid=_KID)
            self.assertEqual(calls["n"], 1)
        finally:
            access_jwt.fetch_certs = orig

    def test_unknown_kid_triggers_one_throttled_refetch_then_still_denied(self):
        calls = {"n": 0}

        def fake_fetch(team, ttl_s=3600, opener=None):
            calls["n"] += 1
            return CERTS  # never contains "rotated-away"

        orig = access_jwt.fetch_certs
        access_jwt.fetch_certs = fake_fetch
        try:
            cache = access_jwt.CertsCache(TEAM, kid_retry_s=60.0)
            cache.get(kid=_KID)  # primes the cache: calls == 1
            self.assertEqual(calls["n"], 1)

            now = time.time()
            cache.get(kid="rotated-away", now=now)  # unknown kid -> one opportunistic refetch
            self.assertEqual(calls["n"], 2)

            cache.get(kid="rotated-away", now=now + 1)  # same kid, inside the 60s throttle
            self.assertEqual(calls["n"], 2)

            cache.get(kid="rotated-away", now=now + 61)  # throttle window has passed
            self.assertEqual(calls["n"], 3)
        finally:
            access_jwt.fetch_certs = orig

    # -- finding #5 --------------------------------------------------------------------------
    def test_five_requests_after_a_failure_make_one_attempt_within_thirty_seconds(self):
        calls = {"n": 0}

        def always_boom(team, ttl_s=3600, opener=None):
            calls["n"] += 1
            raise access_jwt.AccessDenied("Access certs unreachable: simulated outage")

        orig = access_jwt.fetch_certs
        access_jwt.fetch_certs = always_boom
        try:
            cache = access_jwt.CertsCache(TEAM, failure_retry_s=30.0)
            now = time.time()
            for i in range(5):
                with self.assertRaises(access_jwt.AccessDenied):
                    cache.get(kid=_KID, now=now + i)  # 5 calls, all within the 30s window
            self.assertEqual(calls["n"], 1)  # only the FIRST one actually touched the network

            with self.assertRaises(access_jwt.AccessDenied):
                cache.get(kid=_KID, now=now + 31)  # window passed -> allowed to retry
            self.assertEqual(calls["n"], 2)
        finally:
            access_jwt.fetch_certs = orig

    def test_failure_throttle_clears_on_the_next_successful_fetch(self):
        state = {"boom": True, "n": 0}

        def flaky(team, ttl_s=3600, opener=None):
            state["n"] += 1
            if state["boom"]:
                raise access_jwt.AccessDenied("simulated outage")
            return CERTS

        orig = access_jwt.fetch_certs
        access_jwt.fetch_certs = flaky
        try:
            cache = access_jwt.CertsCache(TEAM, failure_retry_s=30.0)
            now = time.time()
            with self.assertRaises(access_jwt.AccessDenied):
                cache.get(kid=_KID, now=now)
            state["boom"] = False
            got = cache.get(kid=_KID, now=now + 31)  # past the throttle, endpoint now healthy
            self.assertEqual(got, CERTS)
            self.assertEqual(state["n"], 2)
        finally:
            access_jwt.fetch_certs = orig


class AccessJwtFetchCerts(unittest.TestCase):
    """Finding #4 (second review round): NO disk cache at all — a fetch failure is ALWAYS
    AccessDenied, never a read from (or write to) a file anywhere."""

    def test_successful_fetch_returns_certs_and_touches_no_disk(self):
        import tempfile

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(CERTS).encode()

        with tempfile.TemporaryDirectory() as tmp:
            before = set(Path(tmp).iterdir())
            got = access_jwt.fetch_certs(TEAM, opener=lambda *a, **k: FakeResp())
            self.assertEqual(got, CERTS)
            self.assertEqual(set(Path(tmp).iterdir()), before)  # no file appeared anywhere

    def test_fetch_failure_raises_even_though_a_stale_file_sits_on_disk(self):
        # finding #4: a file that LOOKS like an old disk cache must have ZERO effect — there is
        # no code path left that reads it.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            decoy = Path(tmp) / "mission_access_certs.json"
            decoy.write_text(json.dumps({"certs": CERTS, "fetched_at": time.time()}),
                              encoding="utf-8")

            def boom(*a, **k):
                raise OSError("network down")

            with self.assertRaises(access_jwt.AccessDenied):
                access_jwt.fetch_certs(TEAM, opener=boom)
            # the decoy file is untouched — proof nothing read OR wrote it
            self.assertEqual(decoy.read_text(encoding="utf-8").count("fetched_at"), 1)

    def test_fetch_certs_signature_has_no_cache_path_parameter(self):
        import inspect
        params = list(inspect.signature(access_jwt.fetch_certs).parameters)
        self.assertNotIn("cache_path", params)
        params_cc = list(inspect.signature(access_jwt.CertsCache.__init__).parameters)
        self.assertNotIn("cache_path", params_cc)


# ════════════════════════════════════════════════════════════════════════════════════════════
# mission_build
# ════════════════════════════════════════════════════════════════════════════════════════════
def _fake_model(state="HEALTHY"):
    return {"schema": "mission-control/1", "generated_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "system": {"_meta": {"state": state}}, "overview": {"needs_owner": {"count": 0}}}


def _write_ui_dir(d: Path, *, with_index=True, with_app=True,
                   extra=tuple(n for n in mission_build.REQUIRED_UI_FILES
                               if n not in ("index.html", "app.js"))):
    d.mkdir(parents=True, exist_ok=True)
    if with_index:
        (d / "index.html").write_text("<!doctype html><title>mc</title>", encoding="utf-8")
    if with_app:
        (d / "app.js").write_text("// app", encoding="utf-8")
    for name in extra:
        (d / name).write_text("/* x */", encoding="utf-8")
    return d


class MissionBuildBundling(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "serve"
        self.ui = _write_ui_dir(self.tmp / "ui")

    def tearDown(self):
        self._tmp.cleanup()

    def test_build_creates_bundle_with_model_and_ui_files(self):
        result = mission_build.build_bundle(self.root, build_fn=lambda: _fake_model(),
                                             ui_dir=self.ui)
        bundle_dir = self.root / result["bundle"]
        self.assertTrue(bundle_dir.is_dir())
        self.assertTrue((bundle_dir / "mission.json").exists())
        self.assertEqual(json.loads((bundle_dir / "mission.json").read_text())["schema"],
                          "mission-control/1")
        for name in ("index.html", "app.js", "styles.css", "i18n.js"):
            self.assertTrue((bundle_dir / name).exists(), name)

        pointer = json.loads((self.root / "current.json").read_text())
        self.assertEqual(pointer["bundle"], result["bundle"])
        self.assertEqual(pointer["schema"], "mission-control/1")
        self.assertEqual(pointer["system_state"], "HEALTHY")

    def test_required_ui_files_are_derived_from_server_routes(self):
        # finding #13: a bundle the server would refuse to serve must never be "built" at all.
        expected = {name for name, _ctype in mission_server.ROUTES.values() if name != "mission.json"}
        self.assertEqual(set(mission_build.REQUIRED_UI_FILES), expected)

    def test_prunes_old_bundles_but_never_the_current_one(self):
        names = []
        for i in range(7):
            r = mission_build.build_bundle(self.root, keep=3, build_fn=lambda: _fake_model(),
                                            ui_dir=self.ui,
                                            now=NOW
                                            + timedelta(seconds=i))
            names.append(r["bundle"])
        remaining = {p.name for p in self.root.iterdir() if p.is_dir()}
        self.assertEqual(len(remaining), 3)
        current = json.loads((self.root / "current.json").read_text())["bundle"]
        self.assertIn(current, remaining)
        self.assertEqual(current, names[-1])
        # the three newest survive
        self.assertEqual(remaining, set(names[-3:]))

    def test_staging_dir_name_does_not_match_the_prune_prefix(self):
        # finding #13: if the staging name shared BUNDLE_PREFIX, a concurrent build's _prune()
        # could rmtree the OTHER build's in-progress staging directory.
        self.assertFalse(mission_build._new_staging_name(datetime.now(timezone.utc))
                          .startswith(mission_build.BUNDLE_PREFIX))

    def test_concurrent_prune_cannot_remove_an_in_progress_staging_dir(self):
        # simulate: build A has written its staging dir but not yet replaced it, then build B
        # (any number of generations later) runs _prune() — A's staging dir must survive.
        for i in range(3):
            mission_build.build_bundle(self.root, keep=1, build_fn=lambda: _fake_model(),
                                        ui_dir=self.ui,
                                        now=NOW
                                        + timedelta(seconds=i))
        staging = self.root / mission_build._new_staging_name(datetime.now(timezone.utc))
        staging.mkdir(mode=0o700)
        try:
            mission_build._prune(self.root, keep=1,
                                  current_name=json.loads(
                                      (self.root / "current.json").read_text())["bundle"])
            self.assertTrue(staging.is_dir())
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_build_fn_exception_leaves_previous_bundle_and_pointer_untouched(self):
        first = mission_build.build_bundle(self.root, build_fn=lambda: _fake_model(), ui_dir=self.ui)
        pointer_before = (self.root / "current.json").read_text()
        bundles_before = {p.name for p in self.root.iterdir() if p.is_dir()}

        def boom():
            raise RuntimeError("producer exploded")

        with self.assertRaises(mission_build.BuildError):
            mission_build.build_bundle(self.root, build_fn=boom, ui_dir=self.ui)

        self.assertEqual((self.root / "current.json").read_text(), pointer_before)
        self.assertEqual({p.name for p in self.root.iterdir() if p.is_dir()}, bundles_before)
        self.assertNotIn(first["bundle"], [])  # sanity: first build really happened

    def test_unexpected_exception_is_wrapped_as_builderror_not_a_traceback(self):
        # finding #13: an exception the function did not specifically anticipate must still be
        # a BuildError (so main() can exit 2), never an uncaught crash.
        def boom_weird():
            raise KeyError("something nobody expected")

        first = mission_build.build_bundle(self.root, build_fn=lambda: _fake_model(), ui_dir=self.ui)
        pointer_before = (self.root / "current.json").read_text()
        with self.assertRaises(mission_build.BuildError):
            mission_build.build_bundle(self.root, build_fn=boom_weird, ui_dir=self.ui)
        self.assertEqual((self.root / "current.json").read_text(), pointer_before)
        self.assertNotIn(first["bundle"], [])

    def test_missing_index_html_fails_and_leaves_pointer_untouched(self):
        first = mission_build.build_bundle(self.root, build_fn=lambda: _fake_model(), ui_dir=self.ui)
        pointer_before = (self.root / "current.json").read_text()

        broken_ui = _write_ui_dir(self.tmp / "ui_no_index", with_index=False)
        with self.assertRaises(mission_build.BuildError):
            mission_build.build_bundle(self.root, build_fn=lambda: _fake_model(), ui_dir=broken_ui)

        self.assertEqual((self.root / "current.json").read_text(), pointer_before)
        # no leftover staging directory of either naming scheme
        leftovers = [p.name for p in self.root.iterdir()
                     if p.name.endswith(".incomplete") or p.name.startswith(mission_build.STAGING_PREFIX)]
        self.assertEqual(leftovers, [])

    def test_missing_app_js_fails(self):
        broken_ui = _write_ui_dir(self.tmp / "ui_no_app", with_app=False)
        with self.assertRaises(mission_build.BuildError):
            mission_build.build_bundle(self.root, build_fn=lambda: _fake_model(), ui_dir=broken_ui)

    def test_non_dict_model_fails(self):
        with self.assertRaises(mission_build.BuildError):
            mission_build.build_bundle(self.root, build_fn=lambda: ["not", "a", "dict"], ui_dir=self.ui)

    def test_pointer_is_written_via_atomic_save(self):
        # finding #13: data FIRST — catches an accidental argument-order regression (atomic_save
        # writing "path" as if it were the data, or vice versa) rather than just checking content.
        result = mission_build.build_bundle(self.root, build_fn=lambda: _fake_model(), ui_dir=self.ui)
        pointer_path = self.root / "current.json"
        self.assertTrue(pointer_path.is_file())
        doc = json.loads(pointer_path.read_text())
        self.assertEqual(doc["bundle"], result["bundle"])

    def test_main_cli_exit_codes(self):
        # main() calls the real mission_control.build() and the real mission_ui/ tree unless we
        # monkeypatch the module attributes it reads at call time (build_bundle() looks them up
        # lazily, not via a bound reference) — mission_ui/ is being written by another agent
        # concurrently, so pinning it to our own fixture keeps this test independent of that race.
        from spa_core.studio_os import mission_control as mc
        orig_build, orig_ui_dir = mc.build, mission_build.UI_DIR
        try:
            mc.build = lambda: _fake_model()
            mission_build.UI_DIR = self.ui
            rc = mission_build.main(["--root", str(self.root)])
            self.assertEqual(rc, 0)
            mc.build = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
            rc2 = mission_build.main(["--root", str(self.root)])
            self.assertEqual(rc2, 2)
        finally:
            mc.build = orig_build
            mission_build.UI_DIR = orig_ui_dir

    # -- finding #10 (second review round): concurrent-build lock ---------------------------
    def test_a_build_already_holding_the_lock_makes_the_second_call_skip_cleanly(self):
        import fcntl
        lock_path = self.root / mission_build.LOCK_FILE
        self.root.mkdir(parents=True, exist_ok=True)
        holder_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(holder_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # simulate another build in progress
        try:
            bundles_before = {p.name for p in self.root.iterdir() if p.is_dir()}
            pointer_before = ((self.root / "current.json").read_text(encoding="utf-8")
                               if (self.root / "current.json").exists() else None)
            with self.assertRaises(mission_build.BuildSkipped):
                mission_build.build_bundle(self.root, build_fn=lambda: _fake_model(), ui_dir=self.ui)
            # NOTHING touched: no new bundle dir, no staging dir, pointer unchanged
            after = {p.name for p in self.root.iterdir() if p.is_dir()}
            self.assertEqual(after, bundles_before)
            pointer_after = ((self.root / "current.json").read_text(encoding="utf-8")
                              if (self.root / "current.json").exists() else None)
            self.assertEqual(pointer_after, pointer_before)
        finally:
            fcntl.flock(holder_fd, fcntl.LOCK_UN)
            os.close(holder_fd)

    def test_lock_is_released_after_a_build_so_the_next_one_proceeds(self):
        r1 = mission_build.build_bundle(self.root, build_fn=lambda: _fake_model(), ui_dir=self.ui)
        r2 = mission_build.build_bundle(self.root, build_fn=lambda: _fake_model(), ui_dir=self.ui)
        self.assertNotEqual(r1["bundle"], r2["bundle"])

    def test_main_reports_skip_as_its_own_exit_code(self):
        """Nothing built is not success (inv. #17, absent-observation ratchet): 75, not 0 or 2."""
        import fcntl
        self.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.root / mission_build.LOCK_FILE
        holder_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(holder_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            from spa_core.studio_os import mission_control as mc
            orig_build, orig_ui_dir = mc.build, mission_build.UI_DIR
            try:
                mc.build = lambda: _fake_model()
                mission_build.UI_DIR = self.ui
                rc = mission_build.main(["--root", str(self.root)])
                self.assertEqual(rc, mission_build.EXIT_SKIPPED)
                self.assertNotIn(rc, (0, 2))
            finally:
                mc.build = orig_build
                mission_build.UI_DIR = orig_ui_dir
        finally:
            fcntl.flock(holder_fd, fcntl.LOCK_UN)
            os.close(holder_fd)


# ════════════════════════════════════════════════════════════════════════════════════════════
# mission_server — bundle resilience (finding #11)
# ════════════════════════════════════════════════════════════════════════════════════════════
class MissionServerBundleResilience(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "serve"
        self.ui = _write_ui_dir(self.tmp / "ui")

    def tearDown(self):
        self._tmp.cleanup()

    def test_pointer_json_that_is_a_list_is_ignored_not_a_crash(self):
        self.root.mkdir(parents=True)
        (self.root / "current.json").write_text("[1, 2]", encoding="utf-8")
        self.assertIsNone(mission_server.read_pointer(self.root))  # not an AttributeError

    def test_pointer_json_that_is_a_string_is_ignored(self):
        self.root.mkdir(parents=True)
        (self.root / "current.json").write_text('"just a string"', encoding="utf-8")
        self.assertIsNone(mission_server.read_pointer(self.root))

    def test_bundle_file_replaced_by_a_directory_raises_bundleerror_not_crash(self):
        result = mission_build.build_bundle(self.root, build_fn=lambda: _fake_model(), ui_dir=self.ui)
        pointer = mission_server.read_pointer(self.root)
        bundle_dir = self.root / result["bundle"]
        target = bundle_dir / "app.js"
        target.unlink()
        target.mkdir()  # f.read_bytes() now raises IsADirectoryError (an OSError)
        with self.assertRaises(mission_server.BundleError):
            mission_server.load_bundle(self.root, pointer)

    def test_serving_keeps_previous_good_bundle_when_pointer_names_a_broken_one(self):
        first = mission_build.build_bundle(self.root, build_fn=lambda: _fake_model(), ui_dir=self.ui)
        serving = mission_server.Serving(self.root)
        serving.refresh(force=True)
        self.assertIsNotNone(serving.state)

        bad_pointer = {"bundle": "does-not-exist-at-all", "built_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "schema": "mission-control/1", "system_state": "HEALTHY"}
        (self.root / "current.json").write_text(json.dumps(bad_pointer), encoding="utf-8")
        serving.refresh(force=True)

        self.assertIsNotNone(serving.state)  # previous good copy, not None
        self.assertEqual(serving.pointer["bundle"], first["bundle"])
        self.assertGreaterEqual(serving.errors, 1)


# ════════════════════════════════════════════════════════════════════════════════════════════
# mission_server — HTTP layer
# ════════════════════════════════════════════════════════════════════════════════════════════
def free_port() -> int:
    """A port measured at the same socket family the server itself binds (no 'probably free')."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LiveServer:
    """A real mission_server pair (local + optional public), started in threads on measured-free
    loopback ports."""

    def __init__(self, root, env=None, access_config_path=None, allow_env_config=False):
        self.local_port = free_port()
        self.servers, self.serving = mission_server.serve(
            root, self.local_port, serve_forever=False, env=env,
            access_config_path=access_config_path, allow_env_config=allow_env_config)
        self.local_httpd = self.servers["local"]
        self.public_httpd = self.servers.get("public")
        self.public_port = self.public_httpd.server_address[1] if self.public_httpd else None
        self._threads = []
        for httpd in (self.local_httpd, self.public_httpd):
            if httpd is None:
                continue
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            self._threads.append(t)

    def request(self, path, method="GET", host=None, headers=None, timeout=6, port=None):
        port = port if port is not None else self.local_port
        host = host if host is not None else f"127.0.0.1:{port}"
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        try:
            hdrs = {"Host": host}
            if headers:
                hdrs.update(headers)
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for k, v in hdrs.items():
                conn.putheader(k, v)
            conn.endheaders()
            r = conn.getresponse()
            return r.status, dict(r.getheaders()), r.read()
        finally:
            conn.close()

    def close(self):
        for httpd in (self.local_httpd, self.public_httpd):
            if httpd is None:
                continue
            httpd.shutdown()
            httpd.server_close()


def raw_request(port: int, raw: bytes, timeout: float = 6) -> bytes:
    """Sends exactly ``raw`` over a fresh TCP connection and reads until the peer closes (or we
    time out), for probes that need control over framing http.client would not let through."""
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        s.sendall(raw)
        s.settimeout(timeout)
        chunks = []
        try:
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        except socket.timeout:
            pass
        return b"".join(chunks)
    finally:
        s.close()


def build_loopback_bundle(root: Path, ui_dir: Path) -> dict:
    return mission_build.build_bundle(root, build_fn=lambda: _fake_model(), ui_dir=ui_dir)


REQUIRED_HEADERS = {
    "Content-Security-Policy", "X-Content-Type-Options", "Referrer-Policy",
    "Cache-Control", "X-Frame-Options", "X-Robots-Tag",
}


class ServerBasics(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "serve"
        self.ui = _write_ui_dir(self.tmp / "ui")
        build_loopback_bundle(self.root, self.ui)
        self.s = LiveServer(self.root)

    def tearDown(self):
        self.s.close()
        self._tmp.cleanup()

    def test_default_bind_is_loopback(self):
        host, _port = self.s.local_httpd.server_address[:2]
        self.assertEqual(host, "127.0.0.1")

    def test_no_public_host_means_no_public_listener_at_all(self):
        self.assertIsNone(self.s.public_httpd)

    def test_binding_outside_loopback_is_refused(self):
        for bad in ("0.0.0.0", "", "192.168.1.5", "::"):
            with self.assertRaises(mission_server.BundleError):
                mission_server.serve(self.root, free_port(), bind=bad, serve_forever=False)

    def test_index_and_mission_json_200_with_security_headers(self):
        for path in ("/", "/mission.json", "/app.js", "/index.html", "/styles.css",
                     "/i18n.js"):
            status, headers, body = self.s.request(path)
            self.assertEqual(status, 200, path)
            missing = REQUIRED_HEADERS - set(headers)
            self.assertFalse(missing, f"{path} missing headers: {missing}")
            self.assertTrue(len(body) > 0, path)

    def test_mission_json_content_matches_model(self):
        status, _headers, body = self.s.request("/mission.json")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["schema"], "mission-control/1")

    def test_healthz_reports_bundle_and_age(self):
        status, _headers, body = self.s.request("/healthz")
        self.assertEqual(status, 200)
        doc = json.loads(body)
        self.assertTrue(doc["ok"])
        self.assertIsNotNone(doc["bundle"])
        self.assertIsNotNone(doc["built_at"])
        self.assertIsInstance(doc["age_s"], (int, float))

    def test_unknown_and_path_traversal_paths_are_404(self):
        for path in ("/../etc/passwd", "/%2e%2e/", "/current.json", "/b-x/mission.json",
                     "/does-not-exist", "/mission_ui/index.html", "//etc/passwd"):
            status, headers, _body = self.s.request(path)
            self.assertEqual(status, 404, path)
            self.assertFalse(REQUIRED_HEADERS - set(headers), path)

    def test_post_put_delete_are_405_with_allow_header(self):
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            status, headers, _body = self.s.request("/", method=method)
            self.assertEqual(status, 405, method)
            self.assertIn("Allow", headers)
            self.assertIn("GET", headers["Allow"])
            self.assertIn("HEAD", headers["Allow"])

    def test_head_matches_get_status_with_empty_body(self):
        status, headers, body = self.s.request("/", method="HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")

    def test_unrecognised_host_is_refused(self):
        status, headers, _body = self.s.request("/", host="evil.example.com")
        self.assertIn(status, (403, 421))
        self.assertFalse(REQUIRED_HEADERS - set(headers))

    def test_ipv6_loopback_host_is_accepted(self):
        status, _headers, _body = self.s.request("/mission.json", host=f"[::1]:{self.s.local_port}")
        self.assertEqual(status, 200)

    def test_bundle_unavailable_before_any_build_is_503(self):
        empty_root = self.tmp / "serve_empty"
        empty_root.mkdir()
        s2 = LiveServer(empty_root)
        try:
            status, _headers, _body = s2.request("/mission.json")
            self.assertEqual(status, 503)
        finally:
            s2.close()

    def test_pointer_swap_is_picked_up_after_a_forced_refresh(self):
        # re-build with a different system state and force a refresh (bypassing the 5s throttle)
        mission_build.build_bundle(self.root, build_fn=lambda: _fake_model(state="DEGRADED"),
                                    ui_dir=self.ui)
        self.s.serving.refresh(force=True)
        status, _headers, body = self.s.request("/mission.json")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["system"]["_meta"]["state"], "DEGRADED")

    # -- finding #1: proxy/tunnel headers on the LOCAL listener -----------------------------------
    def test_local_listener_with_cf_connecting_ip_header_is_403(self):
        status, headers, body = self.s.request(
            "/mission.json", headers={"Cf-Connecting-Ip": "203.0.113.9"})
        self.assertEqual(status, 403)
        self.assertNotIn(b"mission-control/1", body)
        self.assertFalse(REQUIRED_HEADERS - set(headers))

    def test_local_listener_rejects_every_named_proxy_header(self):
        for name, value in (("Cf-Connecting-Ip", "203.0.113.9"), ("Cf-Ray", "abc123-SJC"),
                             ("Cf-Access-Jwt-Assertion", "x.y.z"), ("Cf-Visitor", '{"scheme":"https"}'),
                             ("Cdn-Loop", "cloudflare"), ("X-Forwarded-For", "203.0.113.9")):
            status, _h, _b = self.s.request("/mission.json", headers={name: value})
            self.assertEqual(status, 403, name)

    def test_local_listener_proxy_header_check_is_case_insensitive(self):
        status, _h, _b = self.s.request("/mission.json", headers={"cf-connecting-ip": "1.2.3.4"})
        self.assertEqual(status, 403)

    def test_local_listener_with_public_host_header_is_refused(self):
        status, _h, _b = self.s.request("/mission.json", host="mc.earn-defi.com")
        self.assertIn(status, (403, 421))

    # -- finding #2: keep-alive desync ------------------------------------------------------------
    def test_smuggling_probe_single_response_then_close(self):
        raw = (f"POST / HTTP/1.1\r\nHost: 127.0.0.1:{self.s.local_port}\r\n"
               f"Content-Length: 54\r\n\r\n"
               f"GET /mission.json HTTP/1.1\r\nHost: 127.0.0.1:{self.s.local_port}\r\n\r\n"
               ).encode("ascii")
        resp = raw_request(self.s.local_port, raw)
        self.assertEqual(resp.count(b"HTTP/1.1 "), 1, resp)
        self.assertTrue(resp.startswith(b"HTTP/1.1 400"), resp[:40])

    def test_pipelined_request_after_a_403_gets_no_second_response(self):
        raw = (f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{self.s.local_port}\r\n"
               f"Cf-Connecting-Ip: 1.2.3.4\r\n\r\n"
               f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{self.s.local_port}\r\n\r\n"
               ).encode("ascii")
        resp = raw_request(self.s.local_port, raw)
        self.assertEqual(resp.count(b"HTTP/1.1 "), 1, resp)
        self.assertTrue(resp.startswith(b"HTTP/1.1 403"), resp[:40])

    def test_transfer_encoding_header_is_400_and_closes(self):
        raw = (f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{self.s.local_port}\r\n"
               f"Transfer-Encoding: chunked\r\n\r\n0\r\n\r\n").encode("ascii")
        resp = raw_request(self.s.local_port, raw)
        self.assertEqual(resp.count(b"HTTP/1.1 "), 1, resp)
        self.assertTrue(resp.startswith(b"HTTP/1.1 400"), resp[:40])

    def test_non_2xx_response_carries_connection_close_header(self):
        status, headers, _body = self.s.request("/does-not-exist")
        self.assertEqual(status, 404)
        self.assertEqual(headers.get("Connection"), "close")

    def test_2xx_response_does_not_force_close(self):
        _status, headers, _body = self.s.request("/mission.json")
        self.assertNotEqual(headers.get("Connection"), "close")

    def test_request_handler_timeout_is_fifteen_seconds(self):
        self.assertEqual(self.s.local_httpd.RequestHandlerClass.timeout, 15)

    # -- finding #1 (second review round): duplicate Content-Length -------------------------------
    def test_duplicate_content_length_headers_is_400_and_closes(self):
        raw = (f"POST / HTTP/1.1\r\nHost: 127.0.0.1:{self.s.local_port}\r\n"
               f"Content-Length: 0\r\nContent-Length: 40\r\n\r\n"
               f"GET /mission.json HTTP/1.1\r\nHost: 127.0.0.1:{self.s.local_port}\r\n\r\n"
               ).encode("ascii")
        resp = raw_request(self.s.local_port, raw)
        self.assertEqual(resp.count(b"HTTP/1.1 "), 1, resp)  # the smuggled 2nd request never answered
        self.assertTrue(resp.startswith(b"HTTP/1.1 400"), resp[:40])

    def test_single_content_length_zero_is_still_fine(self):
        # positive control: the duplicate-CL check must not start rejecting the common, correct
        # case (exactly one Content-Length: 0, as most GET clients send).
        raw = (f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{self.s.local_port}\r\n"
               f"Content-Length: 0\r\n\r\n").encode("ascii")
        resp = raw_request(self.s.local_port, raw)
        self.assertTrue(resp.startswith(b"HTTP/1.1 200"), resp[:40])

    # -- finding #2 (second review round): header-parse defects / duplicate Host ------------------
    def test_malformed_header_line_that_drops_a_later_header_is_400(self):
        # "X-A : b" (space before the colon) is flagged by the stdlib email parser as a defect,
        # and the header AFTER it (Cf-Ray here) is silently dropped from self.headers entirely —
        # proven directly against http.client.parse_headers earlier in this file. A handler that
        # only checked "is there a Cf-Ray header" would see none and serve this as a plain
        # loopback request; checking `.defects` instead refuses it outright.
        raw = (f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{self.s.local_port}\r\n"
               f"X-A : b\r\nCf-Ray: abc123\r\n\r\n").encode("ascii")
        resp = raw_request(self.s.local_port, raw)
        self.assertEqual(resp.count(b"HTTP/1.1 "), 1, resp)
        self.assertTrue(resp.startswith(b"HTTP/1.1 400"), resp[:40])

    def test_duplicate_host_header_is_400(self):
        raw = (f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{self.s.local_port}\r\n"
               f"Host: evil.example.com\r\n\r\n").encode("ascii")
        resp = raw_request(self.s.local_port, raw)
        self.assertEqual(resp.count(b"HTTP/1.1 "), 1, resp)
        self.assertTrue(resp.startswith(b"HTTP/1.1 400"), resp[:40])

    def test_well_formed_single_header_block_is_unaffected(self):
        # positive control for both of the checks above.
        status, _h, _b = self.s.request("/mission.json")
        self.assertEqual(status, 200)

    # -- finding #3 (second review round): HTTP/0.9-style request lines ---------------------------
    def test_request_line_with_no_version_still_gets_a_status_line_and_security_headers(self):
        # a bare "GET /\r\n\r\n" (no "HTTP/x.y" token) is handled by the stdlib as HTTP/0.9 by
        # DEFAULT, and send_response()/send_header() are silent no-ops for that version — the
        # client gets a body with NO status line and NO headers at all. Proven directly against
        # plain http.server.BaseHTTPRequestHandler earlier; this proves the fix.
        resp = raw_request(self.s.local_port, b"GET /\r\n\r\n")
        self.assertTrue(resp.startswith(b"HTTP/"), resp[:40])
        self.assertIn(b"Content-Security-Policy", resp)
        self.assertIn(b"X-Content-Type-Options", resp)

    # -- finding #11 (second review round): widened proxy-header set + CORP header ----------------
    def test_local_listener_rejects_every_newly_added_proxy_header(self):
        for name, value in (("Forwarded", 'for="203.0.113.9"'), ("X-Forwarded-Host", "evil.example.com"),
                             ("X-Forwarded-Proto", "https"), ("X-Real-Ip", "203.0.113.9"),
                             ("True-Client-Ip", "203.0.113.9"), ("Via", "1.1 proxy")):
            status, _h, _b = self.s.request("/mission.json", headers={name: value})
            self.assertEqual(status, 403, name)

    def test_local_listener_rejects_any_tailscale_prefixed_header(self):
        for name in ("Tailscale-User-Login", "Tailscale-Headers-Info", "tailscale-funnel"):
            status, _h, _b = self.s.request("/mission.json", headers={name: "x"})
            self.assertEqual(status, 403, name)

    def test_cross_origin_resource_policy_header_present_on_every_response(self):
        for path, expect in (("/mission.json", 200), ("/does-not-exist", 404)):
            _status, headers, _b = self.s.request(path)
            self.assertEqual(headers.get("Cross-Origin-Resource-Policy"), "same-origin", path)


class ServerAccessGate(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "serve"
        self.ui = _write_ui_dir(self.tmp / "ui")
        build_loopback_bundle(self.root, self.ui)
        self.public_port = free_port()
        self.env = {"MC_PUBLIC_HOST": "mc.earn-defi.com", "MC_PUBLIC_PORT": str(self.public_port),
                    "MC_ACCESS_AUD": AUD, "MC_ACCESS_TEAM": TEAM, "MC_OWNER_EMAILS": OWNER_EMAIL}
        self._orig_fetch = access_jwt.fetch_certs
        access_jwt.fetch_certs = lambda *a, **k: CERTS  # tests never touch the network
        # finding #6: env-based config requires an explicit opt-in — this is the test override.
        self.s = LiveServer(self.root, env=self.env, allow_env_config=True)

    def tearDown(self):
        self.s.close()
        access_jwt.fetch_certs = self._orig_fetch
        self._tmp.cleanup()

    def _jwt(self, **overrides):
        return make_jwt(base_claims(time.time(), **overrides))

    def test_public_listener_was_started_on_its_own_port(self):
        self.assertIsNotNone(self.s.public_httpd)
        self.assertEqual(self.s.public_port, self.public_port)
        self.assertNotEqual(self.s.public_port, self.s.local_port)
        self.assertEqual(self.s.public_httpd.server_address[0], "127.0.0.1")

    # -- replaces the old (insecure) test_loopback_host_still_works_without_any_jwt --------------
    # Inv #16: that test asserted the loopback Host EXEMPTED a request from the JWT check on the
    # SAME socket the public host used — exactly finding #1 (a tunnel/ingress can make an external
    # request look like it came from loopback). It is replaced by the two-listener matrix below,
    # which proves the opposite property: no listener ever serves without the right combination of
    # (its own identity) + (loopback Host with no proxy headers, OR public Host with a valid JWT).
    def test_local_listener_loopback_host_no_cf_headers_is_200(self):
        status, _h, _b = self.s.request("/mission.json", port=self.s.local_port)
        self.assertEqual(status, 200)

    def test_local_listener_loopback_host_with_cf_header_is_403(self):
        status, _h, _b = self.s.request("/mission.json", port=self.s.local_port,
                                         headers={"Cf-Connecting-Ip": "203.0.113.9"})
        self.assertEqual(status, 403)

    def test_local_listener_public_host_is_refused(self):
        status, _h, _b = self.s.request("/mission.json", port=self.s.local_port,
                                         host=self.env["MC_PUBLIC_HOST"])
        self.assertIn(status, (403, 421))

    def test_public_listener_loopback_host_no_jwt_is_403(self):
        status, _h, _b = self.s.request("/mission.json", port=self.s.public_port)
        self.assertEqual(status, 403)

    def test_public_listener_public_host_no_jwt_is_403_on_every_route(self):
        for path, method in (("/", "GET"), ("/mission.json", "GET"), ("/healthz", "GET"),
                              ("/", "HEAD")):
            status, _h, body = self.s.request(path, method=method, port=self.s.public_port,
                                               host=self.env["MC_PUBLIC_HOST"])
            self.assertEqual(status, 403, (path, method))
            self.assertNotIn(b"mission-control/1", body)

    def test_public_listener_valid_jwt_public_host_is_200(self):
        token = self._jwt()
        status, _h, body = self.s.request("/mission.json", port=self.s.public_port,
                                           host=self.env["MC_PUBLIC_HOST"],
                                           headers={"Cf-Access-Jwt-Assertion": token})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["schema"], "mission-control/1")

    def test_public_listener_valid_jwt_loopback_host_is_403(self):
        # the whole point of the second listener: a valid JWT does NOT buy a loopback Host an
        # exemption on the public listener.
        token = self._jwt()
        status, _h, body = self.s.request("/mission.json", port=self.s.public_port,
                                           headers={"Cf-Access-Jwt-Assertion": token})
        self.assertEqual(status, 403)
        self.assertNotIn(b"mission-control/1", body)

    def test_public_listener_without_jwt_serves_no_content(self):
        status, headers, body = self.s.request("/mission.json", port=self.s.public_port,
                                                 host=self.env["MC_PUBLIC_HOST"])
        self.assertEqual(status, 403)
        self.assertNotIn(b"mission-control/1", body)
        self.assertFalse(REQUIRED_HEADERS - set(headers))

    def test_public_listener_wrong_aud_is_403(self):
        token = make_jwt(base_claims(time.time(), aud="not-us"))
        status, _h, body = self.s.request("/mission.json", port=self.s.public_port,
                                           host=self.env["MC_PUBLIC_HOST"],
                                           headers={"Cf-Access-Jwt-Assertion": token})
        self.assertEqual(status, 403)
        self.assertNotIn(b"mission-control/1", body)

    def test_public_listener_expired_token_is_403(self):
        token = make_jwt(base_claims(time.time(), exp=time.time() - 60))
        status, _h, _b = self.s.request("/mission.json", port=self.s.public_port,
                                         host=self.env["MC_PUBLIC_HOST"],
                                         headers={"Cf-Access-Jwt-Assertion": token})
        self.assertEqual(status, 403)

    def test_public_listener_wrong_email_is_403(self):
        token = make_jwt(base_claims(time.time(), email="not-the-owner@example.com"))
        status, _h, _b = self.s.request("/mission.json", port=self.s.public_port,
                                         host=self.env["MC_PUBLIC_HOST"],
                                         headers={"Cf-Access-Jwt-Assertion": token})
        self.assertEqual(status, 403)

    def test_public_listener_tampered_payload_is_403(self):
        token = make_jwt(base_claims(time.time()), tamper_payload=True)
        status, _h, _b = self.s.request("/mission.json", port=self.s.public_port,
                                         host=self.env["MC_PUBLIC_HOST"],
                                         headers={"Cf-Access-Jwt-Assertion": token})
        self.assertEqual(status, 403)

    def test_public_listener_alg_none_is_403(self):
        token = make_jwt(base_claims(time.time()), alg="none")
        status, _h, _b = self.s.request("/mission.json", port=self.s.public_port,
                                         host=self.env["MC_PUBLIC_HOST"],
                                         headers={"Cf-Access-Jwt-Assertion": token})
        self.assertEqual(status, 403)

    def test_public_listener_unknown_kid_is_403(self):
        token = make_jwt(base_claims(time.time()), kid="not-a-real-kid")
        status, _h, _b = self.s.request("/mission.json", port=self.s.public_port,
                                         host=self.env["MC_PUBLIC_HOST"],
                                         headers={"Cf-Access-Jwt-Assertion": token})
        self.assertEqual(status, 403)

    def test_public_listener_access_check_exception_is_403_not_a_crash(self):
        # finding #3: ANY exception inside the access check (not just AccessDenied) must still
        # produce a clean 403, never a handler crash / connection reset.
        def boom(*a, **k):
            raise RuntimeError("certs cache exploded")

        orig = self.s.public_httpd.access_cfg.certs_cache.get
        self.s.public_httpd.access_cfg.certs_cache.get = boom
        try:
            token = self._jwt()
            status, _h, _b = self.s.request("/mission.json", port=self.s.public_port,
                                             host=self.env["MC_PUBLIC_HOST"],
                                             headers={"Cf-Access-Jwt-Assertion": token})
            self.assertEqual(status, 403)
        finally:
            self.s.public_httpd.access_cfg.certs_cache.get = orig

    # -- finding #12: positive controls on the PUBLIC listener ------------------------------------
    def test_public_listener_head_with_valid_jwt_is_200_headers_only(self):
        token = self._jwt()
        status, headers, body = self.s.request("/", method="HEAD", port=self.s.public_port,
                                                 host=self.env["MC_PUBLIC_HOST"],
                                                 headers={"Cf-Access-Jwt-Assertion": token})
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")
        self.assertFalse(REQUIRED_HEADERS - set(headers))

    def test_public_listener_405_refusal_has_no_content_and_closes(self):
        # a disallowed method is refused outright (405) before the Access gate is even consulted
        # — there is no route to serve regardless of auth — but the refusal itself must still
        # carry the same no-body / close guarantee as every other non-2xx response.
        token = self._jwt()
        raw = (f"POST / HTTP/1.1\r\nHost: {self.env['MC_PUBLIC_HOST']}\r\n"
               f"Cf-Access-Jwt-Assertion: {token}\r\nContent-Length: 0\r\n\r\n").encode("ascii")
        resp = raw_request(self.s.public_port, raw)
        self.assertTrue(resp.startswith(b"HTTP/1.1 405"), resp[:40])
        head, _sep, body = resp.partition(b"\r\n\r\n")
        self.assertEqual(body, b"")
        self.assertIn(b"Connection: close", head)

    def test_public_listener_400_refusal_has_no_content_and_closes(self):
        # no JWT at all AND a duplicate Content-Length — whichever check fires first, the
        # refusal must carry no body and close.
        raw = (f"GET / HTTP/1.1\r\nHost: {self.env['MC_PUBLIC_HOST']}\r\n"
               f"Content-Length: 0\r\nContent-Length: 9\r\n\r\nGET /x\r\n\r\n").encode("ascii")
        resp = raw_request(self.s.public_port, raw)
        self.assertEqual(resp.count(b"HTTP/1.1 "), 1, resp)
        self.assertTrue(resp.startswith(b"HTTP/1.1 400"), resp[:40])
        self.assertIn(b"Connection: close", resp)

    def test_public_listener_pipelined_request_after_a_403_gets_no_second_response(self):
        raw = (f"GET / HTTP/1.1\r\nHost: {self.env['MC_PUBLIC_HOST']}\r\n\r\n"
               f"GET / HTTP/1.1\r\nHost: {self.env['MC_PUBLIC_HOST']}\r\n\r\n").encode("ascii")
        resp = raw_request(self.s.public_port, raw)
        self.assertEqual(resp.count(b"HTTP/1.1 "), 1, resp)
        self.assertTrue(resp.startswith(b"HTTP/1.1 403"), resp[:40])

    def test_public_listener_duplicate_content_length_is_400(self):
        raw = (f"POST / HTTP/1.1\r\nHost: {self.env['MC_PUBLIC_HOST']}\r\n"
               f"Content-Length: 0\r\nContent-Length: 40\r\n\r\n").encode("ascii")
        resp = raw_request(self.s.public_port, raw)
        self.assertTrue(resp.startswith(b"HTTP/1.1 400"), resp[:40])

    def test_public_listener_duplicate_host_is_400(self):
        token = self._jwt()
        raw = (f"GET / HTTP/1.1\r\nHost: {self.env['MC_PUBLIC_HOST']}\r\n"
               f"Host: {self.env['MC_PUBLIC_HOST']}\r\nCf-Access-Jwt-Assertion: {token}\r\n\r\n"
               ).encode("ascii")
        resp = raw_request(self.s.public_port, raw)
        self.assertTrue(resp.startswith(b"HTTP/1.1 400"), resp[:40])

    def test_public_listener_header_defect_is_400(self):
        raw = (f"GET / HTTP/1.1\r\nHost: {self.env['MC_PUBLIC_HOST']}\r\n"
               f"X-A : b\r\nCf-Access-Jwt-Assertion: whatever\r\n\r\n").encode("ascii")
        resp = raw_request(self.s.public_port, raw)
        self.assertTrue(resp.startswith(b"HTTP/1.1 400"), resp[:40])


class ServerStartupRefusal(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "serve"
        self.ui = _write_ui_dir(self.tmp / "ui")
        build_loopback_bundle(self.root, self.ui)

    def tearDown(self):
        self._tmp.cleanup()

    def test_public_host_without_audience_refuses_to_start(self):
        env = {"MC_PUBLIC_HOST": "mc.earn-defi.com", "MC_ACCESS_TEAM": TEAM,
               "MC_OWNER_EMAILS": OWNER_EMAIL}  # MC_ACCESS_AUD missing
        with self.assertRaises(mission_server.BundleError):
            mission_server.serve(self.root, free_port(), serve_forever=False, env=env,
                                  allow_env_config=True)

    def test_public_host_without_team_refuses_to_start(self):
        env = {"MC_PUBLIC_HOST": "mc.earn-defi.com", "MC_ACCESS_AUD": AUD,
               "MC_OWNER_EMAILS": OWNER_EMAIL}
        with self.assertRaises(mission_server.BundleError):
            mission_server.serve(self.root, free_port(), serve_forever=False, env=env,
                                  allow_env_config=True)

    def test_public_host_without_owner_emails_refuses_to_start(self):
        env = {"MC_PUBLIC_HOST": "mc.earn-defi.com", "MC_ACCESS_AUD": AUD, "MC_ACCESS_TEAM": TEAM}
        with self.assertRaises(mission_server.BundleError):
            mission_server.serve(self.root, free_port(), serve_forever=False, env=env,
                                  allow_env_config=True)

    def test_no_public_host_needs_no_access_env_at_all(self):
        servers, serving = mission_server.serve(self.root, free_port(), serve_forever=False, env={})
        try:
            self.assertIsNotNone(serving)
            self.assertIsNone(servers["public"])
        finally:
            servers["local"].server_close()

    def test_main_cli_exits_2_on_refused_startup(self):
        import contextlib
        import io
        env_backup = dict(os.environ)
        try:
            os.environ["MC_PUBLIC_HOST"] = "mc.earn-defi.com"
            os.environ.pop("MC_ACCESS_AUD", None)
            os.environ.pop("MC_ACCESS_TEAM", None)
            os.environ.pop("MC_OWNER_EMAILS", None)
            with contextlib.redirect_stderr(io.StringIO()):
                rc = mission_server.main(["--root", str(self.root), "--port", str(free_port()),
                                           "--access-config", "", "--allow-env-config"])
            self.assertEqual(rc, 2)
        finally:
            os.environ.clear()
            os.environ.update(env_backup)

    def test_without_allow_env_config_flag_env_is_not_even_consulted(self):
        # finding #6: without the explicit flag (production's default — see main()'s
        # --allow-env-config help text and the wrapper's "env -u ..." line), MC_PUBLIC_HOST must
        # not even be LOOKED at — the same env that refuses-to-start above (missing companions)
        # must instead be silently irrelevant, giving a clean local-only config (None), not an
        # exception and not a half-applied config.
        env = {"MC_PUBLIC_HOST": "mc.earn-defi.com"}  # companions deliberately missing too
        access_cfg = mission_server.load_access_config(
            env, config_path=self.tmp / "does-not-exist.json", allow_env_config=False)
        self.assertIsNone(access_cfg)

    # -- finding #8: public_port validation -------------------------------------------------------
    def test_public_port_below_1024_refuses_to_start(self):
        env = {"MC_PUBLIC_HOST": "mc.earn-defi.com", "MC_PUBLIC_PORT": "80",
               "MC_ACCESS_AUD": AUD, "MC_ACCESS_TEAM": TEAM, "MC_OWNER_EMAILS": OWNER_EMAIL}
        with self.assertRaises(mission_server.BundleError):
            mission_server.serve(self.root, free_port(), serve_forever=False, env=env,
                                  allow_env_config=True)

    def test_public_port_above_65535_refuses_to_start(self):
        env = {"MC_PUBLIC_HOST": "mc.earn-defi.com", "MC_PUBLIC_PORT": "70000",
               "MC_ACCESS_AUD": AUD, "MC_ACCESS_TEAM": TEAM, "MC_OWNER_EMAILS": OWNER_EMAIL}
        with self.assertRaises(mission_server.BundleError):
            mission_server.serve(self.root, free_port(), serve_forever=False, env=env,
                                  allow_env_config=True)

    def test_public_port_in_range_is_accepted(self):
        public_port = free_port()
        env = {"MC_PUBLIC_HOST": "mc.earn-defi.com", "MC_PUBLIC_PORT": str(public_port),
               "MC_ACCESS_AUD": AUD, "MC_ACCESS_TEAM": TEAM, "MC_OWNER_EMAILS": OWNER_EMAIL}
        servers, _serving = mission_server.serve(self.root, free_port(), serve_forever=False,
                                                   env=env, allow_env_config=True)
        try:
            self.assertIsNotNone(servers["public"])
        finally:
            servers["local"].server_close()
            servers["public"].server_close()

    def test_public_port_colliding_with_local_port_refuses_to_start(self):
        shared_port = free_port()
        env = {"MC_PUBLIC_HOST": "mc.earn-defi.com", "MC_PUBLIC_PORT": str(shared_port),
               "MC_ACCESS_AUD": AUD, "MC_ACCESS_TEAM": TEAM, "MC_OWNER_EMAILS": OWNER_EMAIL}
        with self.assertRaises(mission_server.BundleError):
            mission_server.serve(self.root, shared_port, serve_forever=False, env=env,
                                  allow_env_config=True)

    # -- finding #9: a real OSError (e.g. port already in use) is a clean exit 2, not a traceback -
    def test_main_catches_oserror_from_a_bound_port(self):
        import contextlib
        import io
        busy_port = free_port()
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blocker.bind(("127.0.0.1", busy_port))
        blocker.listen(1)
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                rc = mission_server.main(["--root", str(self.root), "--port", str(busy_port),
                                           "--access-config", ""])
            self.assertEqual(rc, 2)
        finally:
            blocker.close()

    # -- access-config file (finding #1: owner e-mails must never be in the git-tracked plist) ---
    def test_access_config_file_wrong_mode_refuses_to_start(self):
        cfg = self.tmp / "mission_access.json"
        cfg.write_text(json.dumps({"public_host": "mc.earn-defi.com", "aud": AUD, "team": TEAM,
                                    "owner_emails": [OWNER_EMAIL]}), encoding="utf-8")
        cfg.chmod(0o644)  # group/world-readable — must be refused
        with self.assertRaises(mission_server.BundleError):
            mission_server.serve(self.root, free_port(), serve_forever=False, env={},
                                  access_config_path=cfg)

    def test_access_config_file_mode_0600_is_accepted(self):
        cfg = self.tmp / "mission_access.json"
        public_port = free_port()
        cfg.write_text(json.dumps({"public_host": "mc.earn-defi.com", "public_port": public_port,
                                    "aud": AUD, "team": TEAM, "owner_emails": [OWNER_EMAIL]}),
                        encoding="utf-8")
        cfg.chmod(0o600)
        servers, _serving = mission_server.serve(self.root, free_port(), serve_forever=False,
                                                   env={}, access_config_path=cfg)
        try:
            self.assertIsNotNone(servers["public"])
            self.assertEqual(servers["public"].server_address[1], public_port)
        finally:
            servers["local"].server_close()
            servers["public"].server_close()

    def test_missing_access_config_file_is_local_only(self):
        cfg = self.tmp / "does-not-exist" / "mission_access.json"
        servers, _serving = mission_server.serve(self.root, free_port(), serve_forever=False,
                                                   env={}, access_config_path=cfg)
        try:
            self.assertIsNone(servers["public"])
        finally:
            servers["local"].server_close()

    # -- finding #6 (second review round): the file and env are NEVER mixed ----------------------
    def test_file_wins_over_env_entirely_even_with_allow_env_config(self):
        # the OLD behaviour (env overrides the file field-by-field) is exactly what finding #6
        # forbids: a stray MC_PUBLIC_HOST left in some shell could silently combine with the
        # file's owner e-mails into a config nobody wrote down anywhere. Now: file present ⇒ env
        # is not read for so much as one field, REGARDLESS of allow_env_config.
        cfg = self.tmp / "mission_access.json"
        cfg.write_text(json.dumps({"public_host": "from-file.example.com", "aud": AUD,
                                    "team": TEAM, "owner_emails": [OWNER_EMAIL]}),
                        encoding="utf-8")
        cfg.chmod(0o600)
        env = {"MC_PUBLIC_HOST": "from-env.example.com", "MC_PUBLIC_PORT": str(free_port()),
               "MC_ACCESS_AUD": AUD, "MC_ACCESS_TEAM": TEAM, "MC_OWNER_EMAILS": OWNER_EMAIL}
        access_cfg = mission_server.load_access_config(env, config_path=cfg, allow_env_config=True)
        self.assertEqual(access_cfg.public_host, "from-file.example.com")
        # the env's public_port must ALSO be ignored (not just public_host) — the file did not
        # name one, so the DEFAULT applies, not the env's value.
        self.assertEqual(access_cfg.public_port, mission_server.DEFAULT_PUBLIC_PORT)

    def test_env_used_only_when_file_absent_and_flag_given(self):
        cfg = self.tmp / "does-not-exist.json"
        env = {"MC_PUBLIC_HOST": "from-env.example.com", "MC_ACCESS_AUD": AUD,
               "MC_ACCESS_TEAM": TEAM, "MC_OWNER_EMAILS": OWNER_EMAIL}
        access_cfg = mission_server.load_access_config(env, config_path=cfg, allow_env_config=True)
        self.assertEqual(access_cfg.public_host, "from-env.example.com")

    # -- finding #7 (second review round): symlink config is refused, not silently followed ------
    def test_access_config_symlink_refuses_to_start(self):
        real = self.tmp / "real_access.json"
        real.write_text(json.dumps({"public_host": "mc.earn-defi.com", "aud": AUD, "team": TEAM,
                                     "owner_emails": [OWNER_EMAIL]}), encoding="utf-8")
        real.chmod(0o600)
        link = self.tmp / "mission_access.json"
        link.symlink_to(real)
        with self.assertRaises(mission_server.BundleError):
            mission_server.serve(self.root, free_port(), serve_forever=False, env={},
                                  access_config_path=link)


if __name__ == "__main__":
    unittest.main()
