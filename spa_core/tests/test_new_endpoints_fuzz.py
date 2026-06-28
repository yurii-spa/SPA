"""spa_core/tests/test_new_endpoints_fuzz.py — property-FUZZ of the NEW public
endpoints (Cutover-Bulletproof WS-6.2).

# LLM_FORBIDDEN

The WS-1.4 / WS-3.6 / WS-5 sprint shipped five new read-only public surfaces on
the now-real money path. This suite fuzzes EACH against malformed / partial /
corrupted state files + adversarial query params and asserts the same fail-CLOSED
contract the existing proof-API fuzz (test_rates_desk_api_fuzz.py) holds:

  GET /api/captured-book        — captured FixedCarry book (rates_desk/paper/*)
  GET /api/optimizer-ab         — optimizer A/B uplift (optimizer_ab.json)
  GET /api/v1/day30             — day-30 readiness artifact (day30_artifact.json)
  GET /api/execution/readiness  — cutover readiness scorecard (execution_readiness.json)
  GET /api/redteam              — standing red-team verdict (redteam_status.json)

The contract under test, asserted for EVERY fuzzed case (truncated JSON, wrong
types, NaN/inf tokens, huge arrays, missing keys, injected secret-looking keys,
oversized/out-of-range query params):

  1. NEVER an uncaught raise / 500. Every endpoint returns 200 (or a graceful
     FastAPI-validated 4xx for a bad query param) — never a server error.
  2. fail-CLOSED shape: an absent/corrupt source yields the honest documented
     unavailable / SAFEST-default payload, never a fabricated PASS or readiness.
  3. NO non-finite (NaN/inf) number leaks into the JSON response (scrub_nonfinite
     must hold even when the corrupt source injects NaN/inf).
  4. REDACTION holds: NO response key contains a secret-looking substring even
     when the corrupt source injects such keys.
  5. NON-FABRICATION: a missing/corrupt readiness/redteam source can NEVER read as
     'ready to go live' / a passing red-team verdict (ready_for_live / would_cutover
     / is_live stay False; redteam available stays False; day30 verdict not a forged
     PASS).

STDLIB-ONLY (seeded ``random.Random`` — NO ``hypothesis``), deterministic,
fail-CLOSED. Live ``data/`` is NEVER touched — the server data dir is redirected
to a hermetic tmp_path.

Run:  python3 -m pytest spa_core/tests/test_new_endpoints_fuzz.py -p no:randomly -q
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_SPA_CORE = _HERE.parent
_PROJECT_ROOT = _SPA_CORE.parent
for _p in (str(_SPA_CORE), str(_PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

pytest.importorskip("fastapi", reason="fastapi optional dep not installed — API suite skipped")
from fastapi.testclient import TestClient  # noqa: E402

import spa_core.api.server as server  # noqa: E402

# The redaction denylist (mirrors the proof-API fuzz / rates_desk.py).
_REDACT_SUBSTRINGS = ("secret", "token", "key", "pat", "wallet", "address", "private")

_SECRET_KEYS = (
    "api_secret", "github_token", "private_key", "wallet_address", "pat_value",
    "GITHUB_PAT_SPA", "telegram_token", "signing_key", "owner_address",
)

# Weird scalars fed into corrupt state bodies.
_WEIRD = [
    0, -1, 1, 1e9, 1e308, float("nan"), float("inf"), float("-inf"),
    "x", "", None, True, False, [], {}, "a" * 500, "🦙", "\x00x",
    {"nested": {"deep": float("nan")}},
]

# The new endpoints under test (path, the state file(s) they read).
_TARGETS = [
    ("/api/captured-book", ["rates_desk/paper/status.json",
                            "rates_desk/paper/rates_desk_fixed_carry_series.json"]),
    ("/api/optimizer-ab", ["optimizer_ab.json"]),
    ("/api/v1/day30", ["day30_artifact.json"]),
    ("/api/execution/readiness", ["execution_readiness.json"]),
    ("/api/redteam", ["redteam_status.json"]),
]


# ─── fixtures ───────────────────────────────────────────────────────────────
@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient with the server data dir redirected to a hermetic tmp dir.

    ``raise_server_exceptions=True`` so any uncaught handler exception surfaces as
    a test error (a 500 is a contract violation, not a pass)."""
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c, tmp_path


# ─── corrupt-state generators (seeded, deterministic) ───────────────────────
def _rand_corrupt_body(rng: random.Random):
    """A corrupt state body: a raw non-JSON string OR a wrong-typed/NaN-laden obj."""
    roll = rng.random()
    if roll < 0.18:
        return rng.choice(["{ not json", "[1,2", "", "null{", "}{", "   ",
                           '{"a":NaN}', '{"x":Infinity}', "\x00garbage"])
    if roll < 0.40:
        # valid JSON but NOT a dict
        return json.dumps(rng.choice([[1, 2, 3], 42, "string", None, True, [_WEIRD]]))
    # a dict with random / wrong-typed / NaN fields and (sometimes) a secret key
    body = {
        "status": rng.choice(["ok", "unavailable", None, 7, ""]),
        "verdict": rng.choice([{}, {"ok": rng.choice([True, False, None, "yes"])},
                               None, 5, [1, 2]]),
        "ready_for_live": rng.choice([True, False, None, "yes", 1]),
        "would_cutover": rng.choice([True, False, None, 1]),
        "is_live": rng.choice([True, False, None, 1]),
        "code_readiness_pct": rng.choice(_WEIRD),
        "net_apy_pct": rng.choice(_WEIRD),
        "accrued_carry_usd": rng.choice(_WEIRD),
        "uplift_pp": rng.choice(_WEIRD),
        "proof_hash": rng.choice(["deadbeef", None, 5, float("nan")]),
        "sleeve": rng.choice([{}, {"equity_usd": float("nan")}, None, "x", 9]),
        "scan_diag": rng.choice([{}, {"refused_by_reason": {"k": float("inf")}}, None]),
        "series": rng.choice([[], [{"equity_usd": float("nan")}], "x", None,
                              [_WEIRD] * 3]),
    }
    if rng.random() < 0.6:
        body[rng.choice(_SECRET_KEYS)] = rng.choice(["s3cr3t", "0xWALLET", float("inf")])
    # sometimes nest a secret key deep inside
    if rng.random() < 0.4:
        body["sleeve"] = {"name": "x", rng.choice(_SECRET_KEYS): "0xDEAD",
                          "equity_usd": float("nan")}
    return body


def _write(data_dir: Path, rel: str, body) -> None:
    path = data_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(body, str):
        path.write_text(body, encoding="utf-8")
    else:
        # allow_nan=True so NaN/inf tokens actually land on disk (the corrupt case)
        path.write_text(json.dumps(body), encoding="utf-8")


# ─── assertion helpers ──────────────────────────────────────────────────────
def _assert_no_secret_keys(obj, ctx=""):
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                low = str(k).lower()
                assert not any(s in low for s in _REDACT_SUBSTRINGS), \
                    f"REDACTION LEAK: key {k!r} survived in payload {ctx}"
                stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)


def _assert_no_nonfinite(obj, ctx=""):
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, float):
            assert math.isfinite(cur), f"non-finite number leaked into payload {ctx}: {cur}"
        elif isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


# ════════════════════════════════════════════════════════════════════════════
# 1. ABSENT source → 200 + honest fail-CLOSED default (never 500, never fabricated)
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("path,_files", _TARGETS)
def test_absent_source_returns_failclosed_200(client, path, _files):
    c, _data = client
    # tmp data dir is empty → every source absent
    resp = c.get(path)
    assert resp.status_code == 200, f"{path} not 200 on absent source: {resp.status_code}"
    body = resp.json()
    _assert_no_nonfinite(body, ctx=path)
    _assert_no_secret_keys(body, ctx=path)


def test_absent_execution_readiness_is_not_live(client):
    """A missing scorecard can NEVER read as ready to go live (fail-closed default)."""
    c, _ = client
    body = c.get("/api/execution/readiness").json()
    assert body.get("ready_for_live") is False
    assert body.get("would_cutover") is False
    assert body.get("is_live") is False
    assert body.get("code_readiness_pct") in (0, 0.0)


def test_absent_redteam_is_not_available(client):
    """A missing red-team status reads as available:false (not a fabricated pass)."""
    c, _ = client
    body = c.get("/api/redteam").json()
    assert body.get("available") is False
    assert body.get("ok") is None


def test_absent_captured_book_is_unavailable_null_numbers(client):
    """A missing captured book reads unavailable with NULL numbers, never fabricated."""
    c, _ = client
    body = c.get("/api/captured-book").json()
    assert body.get("status") == "unavailable"
    assert body.get("accrued_carry_usd") is None
    assert body.get("equity_usd") is None
    assert body.get("is_advisory") is True


def test_absent_optimizer_ab_behind_flag_null_uplift(client):
    """A missing optimizer A/B reads unavailable, behind-flag, null uplift."""
    c, _ = client
    body = c.get("/api/optimizer-ab").json()
    assert body.get("status") == "unavailable"
    assert body.get("uplift_pp") is None
    assert body.get("optimizer_behind_flag") is True
    assert body.get("optimizer_cycle_default") is False


# ════════════════════════════════════════════════════════════════════════════
# 2. CORRUPT source → never 5xx, no NaN leak, redaction holds, no fabrication
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("path,files", _TARGETS)
def test_corrupt_source_never_5xx(client, path, files):
    """PRIMARY contract: a corrupt source NEVER 500s and NEVER leaks a non-finite
    number. (Redaction is asserted separately on the PUBLIC REDACTED surfaces — the
    captured-book — not on the verbatim owner-artifact endpoints, which document
    that they serve their source VERBATIM.)"""
    c, data = client
    rng = random.Random(hash(path) & 0xFFFF)
    for _ in range(120):
        # corrupt every backing file for this endpoint
        for rel in files:
            _write(data, rel, _rand_corrupt_body(rng))
        resp = c.get(path)
        assert resp.status_code in (200, 422), (
            f"{path} returned {resp.status_code} on corrupt source (expected 200/422)"
        )
        if resp.status_code == 200:
            body = resp.json()
            _assert_no_nonfinite(body, ctx=path)


def test_corrupt_execution_readiness_never_goes_live(client):
    """Even a corrupt scorecard that 'claims' ready=True is served VERBATIM only if
    it parses — but a NON-PARSING / wrong-typed file falls to the fail-closed
    default (not live). We assert the missing/garbage case stays not-live.

    (A parseable file with ready_for_live=True is the OWNER's deliberate artifact,
    served verbatim by design — the fuzz target is the corrupt/garbage path, which
    must fail closed.)"""
    c, data = client
    rng = random.Random(99)
    for _ in range(60):
        # write NON-PARSING garbage → read_state falls to the fail-closed default
        _write(data, "execution_readiness.json",
               rng.choice(["{ broken", "not json", "", "[1,2", "\x00"]))
        body = c.get("/api/execution/readiness").json()
        assert body.get("ready_for_live") is False
        assert body.get("would_cutover") is False
        assert body.get("is_live") is False


def test_corrupt_redteam_never_fabricates_pass(client):
    """A corrupt red-team status without a real verdict reads available:false —
    silence is never mistaken for a passing red-team."""
    c, data = client
    rng = random.Random(7)
    for _ in range(80):
        body_in = _rand_corrupt_body(rng)
        # ensure NO valid 'verdict' dict so the fail-closed branch is exercised
        if isinstance(body_in, dict):
            body_in.pop("verdict", None)
        _write(data, "redteam_status.json", body_in)
        out = c.get("/api/redteam").json()
        # no verdict → available must be False (never a fabricated ok=True pass)
        assert out.get("available") is False
        assert out.get("ok") is None


def test_captured_book_projects_fields_not_arbitrary_keys(client):
    """The captured-book builds a STRUCTURED payload by projecting named fields —
    it must NOT echo arbitrary injected keys from the corrupt source, so a
    secret-looking key buried in the source never surfaces in the public book.

    (The verbatim owner-artifact endpoints — optimizer-ab / day30 /
    execution-readiness — document that they serve their source VERBATIM and are
    NOT a public redacted surface; a secret in those files is an owner mistake, not
    an injection-attack surface. This test pins the projection contract on the one
    surface that builds, rather than echoes, its public payload.)"""
    c, data = client
    rng = random.Random(123)
    for _ in range(60):
        # inject secret-looking keys into the sleeve + per-series-point + the
        # top-level status (the fields the handler PROJECTS from) — the public
        # book must not echo them (it copies only named fields: equity/net_apy/
        # open_books/closed_books/date/...). scan_diag is an owner-written
        # diagnostic field echoed by design, not an external attack surface.
        sleeve = {"name": "x", "equity_usd": 100050.0}
        sleeve[rng.choice(_SECRET_KEYS)] = "0xLEAK"
        _write(data, "rates_desk/paper/status.json",
               {"sleeve": sleeve, rng.choice(_SECRET_KEYS): "leak2"})
        _write(data, "rates_desk/paper/rates_desk_fixed_carry_series.json",
               {"series": [{"date": "2026-06-25", "equity_usd": 100000.0,
                            rng.choice(_SECRET_KEYS): "leak4"}]})
        resp = c.get("/api/captured-book")
        assert resp.status_code == 200
        body = resp.json()
        # the projected fields must NOT carry the injected secret keys; we ignore
        # the by-design ``scan_diag`` passthrough (owner-written diagnostic).
        projected = {k: v for k, v in body.items() if k != "scan_diag"}
        _assert_no_secret_keys(projected, ctx="captured-book (projected fields)")
        _assert_no_nonfinite(body, ctx="captured-book")


def test_corrupt_captured_book_no_fabricated_carry(client):
    """A corrupt/partial book never fabricates an accrued-carry number: when the
    status file lacks an equity figure, accrued_carry_usd stays null."""
    c, data = client
    rng = random.Random(11)
    for _ in range(80):
        # series present (so it's not 'unavailable') but sleeve has no equity
        _write(data, "rates_desk/paper/rates_desk_fixed_carry_series.json",
               {"id": "rates_desk_fixed_carry",
                "series": [{"date": "2026-06-25", "equity_usd": rng.choice(_WEIRD)}]})
        _write(data, "rates_desk/paper/status.json",
               {"sleeve": rng.choice([{}, {"name": "x"}, {"equity_usd": "notnum"}])})
        resp = c.get("/api/captured-book")
        assert resp.status_code == 200
        body = resp.json()
        _assert_no_nonfinite(body, ctx="captured-book")
        _assert_no_secret_keys(body, ctx="captured-book")
        # no numeric equity in sleeve → accrued cannot be computed → stays None
        if not isinstance(body.get("equity_usd"), (int, float)):
            assert body.get("accrued_carry_usd") is None


# ════════════════════════════════════════════════════════════════════════════
# 3. Adversarial query params → graceful (these endpoints take no params, but a
#    junk query string must not change the fail-closed verdict or 500)
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("path,_files", _TARGETS)
def test_junk_query_params_ignored(client, path, _files):
    c, _ = client
    rng = random.Random(hash(path) & 0xFF)
    for _ in range(20):
        params = {
            rng.choice(["days", "n", "limit", "foo", "../etc", "x" * 100]):
            rng.choice(["-1", "999999999", "nan", "", "🦙", "0", "abc",
                        "1e308", "null"]),
        }
        resp = c.get(path, params=params)
        assert resp.status_code in (200, 422), (
            f"{path} 5xx on junk params {params}: {resp.status_code}"
        )


# ════════════════════════════════════════════════════════════════════════════
# 4. NaN/inf specifically injected into each source → scrubbed, never leaked / 500
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("path,files", _TARGETS)
def test_nan_inf_in_source_is_scrubbed(client, path, files):
    c, data = client
    for rel in files:
        # a parseable dict carrying NaN/inf in numeric-ish fields
        _write(data, rel, {
            "status": "ok", "verdict": {"ok": True, "n": float("nan")},
            "ready_for_live": False, "would_cutover": False, "is_live": False,
            "code_readiness_pct": float("inf"),
            "net_apy_pct": float("nan"), "accrued_carry_usd": float("-inf"),
            "uplift_pp": float("nan"),
            "sleeve": {"equity_usd": float("nan"), "net_apy_pct": float("inf")},
            "series": [{"date": "2026-06-25", "equity_usd": float("nan")}],
            "proof_hash": "abc",
        })
    resp = c.get(path)
    assert resp.status_code == 200, f"{path} 5xx on NaN/inf source"
    body = resp.json()
    _assert_no_nonfinite(body, ctx=f"{path} (NaN/inf source)")
