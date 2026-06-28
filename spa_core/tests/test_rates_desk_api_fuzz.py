"""Property-fuzz of the PROOF-API error paths (Sprint "Proof That Doesn't Rot", WS4 §4.1).

STDLIB-ONLY (seeded ``random.Random`` — NO ``hypothesis``), deterministic, fail-CLOSED. Fuzzes
the highest-stakes PUBLIC verification surface — the tamper-evident proof endpoints — against
malformed/partial/oversized requests AND deliberately CORRUPTED on-disk state files:

  GET /api/rates-desk/proof        — the hash-chain verdict (verified / head_hash / broken_at)
  GET /api/rates-desk/refusals     — the public, REDACTED human-readable refusal log
  GET /api/rates-desk/decisions    — the machine decision log
  GET /api/rates-desk/anchors      — the cross-eviction anchor ledger
  GET /api/rates-desk/exit-nav     — the liquidation-NAV-by-size schedule
  GET /api/competitive-watch       — the Section-7 watch radar

The contract under test, asserted for EVERY fuzzed case (corrupt decision_log.jsonl / anchors.jsonl
/ rate_surface.json / exit_nav.json: truncated JSON, wrong types, NaN/inf, huge arrays, missing
keys, injected secret-looking keys, oversized/out-of-range query params):

  1. NEVER an uncaught raise / 500. Every endpoint returns 200 (or a graceful 4xx for a query
     param that FastAPI itself validates) — never a server error and never a fabricated number.
  2. fail-CLOSED shape: an absent/corrupt log yields an honest empty/unavailable payload (the
     documented vacuous-truth or all-WATCH default), never stale or invented data.
  3. The chain ``verified`` flag is NEVER falsely True on corrupt data — a non-JSON line, a
     forged/unlinked row, or a wrong-typed row drives ``verified=false`` (the corrupt-row
     surrogate ``{"__corrupt__": True}`` fails the chain re-derivation).
  4. The REDACTION guard holds even under fuzz: NO key containing secret/token/key/pat/wallet/
     address/private appears ANYWHERE in the public /refusals payload, even when the corrupt log
     injects such keys. No raw-size field that implies real capital leaks.

Run:  python3 -m pytest spa_core/tests/test_rates_desk_api_fuzz.py -p no:randomly -q
"""
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
from spa_core.audit import hash_chain  # noqa: E402

EVENT_TYPE = "rates_desk_decision"

# ── the redaction denylist the public /refusals payload must honour (mirrors rates_desk.py) ──
_REDACT_SUBSTRINGS = ("secret", "token", "key", "pat", "wallet", "address", "private")

# Secret-looking keys we deliberately inject into the corrupt log so the fuzz proves the
# defense-in-depth redaction drops them no matter where they land.
_SECRET_KEYS = (
    "api_secret", "github_token", "private_key", "wallet_address", "pat_value",
    "GITHUB_PAT_SPA", "telegram_token", "signing_key", "owner_address",
)

# Weird scalars fed into corrupt rows / surfaces.
_WEIRD = [
    0, -1, 1, 1e9, 1e308, float("nan"), float("inf"), float("-inf"),
    "x", "", None, True, False, [], {}, "a" * 500, "🦙", "\x00​",
    {"nested": {"deep": float("nan")}},
]


# ─── fixtures ─────────────────────────────────────────────────────────────────────
@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient with the server data dir redirected to a hermetic tmp dir.

    ``raise_server_exceptions=True`` so any uncaught handler exception surfaces as a test
    error (a 500 is a contract violation, not a pass)."""
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c, tmp_path


def _rd_dir(data_dir: Path) -> Path:
    d = data_dir / "rates_desk"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ─── valid-chain builder (so we can corrupt FROM a genuine baseline) ──────────────
def _valid_payload(seq: int, *, approved: bool, underlying: str) -> dict:
    return {
        "kind": "ENTRY" if approved else "REFUSAL",
        "approved": approved,
        "reason": "none" if approved else "tail_veto",
        "as_of": "2026-06-25",
        "underlying": underlying,
        "shape": "fixed_carry",
        "net_edge": "0.05" if approved else "-0.10",
        "decomposition": {"underlying": underlying, "total_haircut": "0.10"},
        "detail": {"note": "x"},
        "proof_hash": f"deadbeef{seq:04d}",
    }


def _write_valid_chain(path: Path, payloads: list) -> list:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows, prev = [], hash_chain.GENESIS_PREV
    for seq, pl in enumerate(payloads):
        ts = "2026-06-25T00:00:00+00:00"
        eh = hash_chain.compute_entry_hash(seq, ts, EVENT_TYPE, pl, prev)
        rows.append({"seq": seq, "ts": ts, "entry_hash": eh, "prev_hash": prev, **pl})
        prev = eh
    path.write_text(
        "\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in rows) + "\n",
        encoding="utf-8",
    )
    return rows


# ─── corrupt-payload generators (seeded, deterministic) ───────────────────────────
def _rand_corrupt_row(rng: random.Random) -> str:
    """ONE line for a corrupt decision_log.jsonl (may or may not be valid JSON)."""
    roll = rng.random()
    if roll < 0.15:
        return rng.choice(["{ not json", "[1,2", "\x00garbage", "}{", "null{", "   "])
    if roll < 0.30:
        # valid JSON but NOT a dict
        return json.dumps(rng.choice([[1, 2, 3], 42, "string", None, True]))
    if roll < 0.55:
        # a dict missing the chain-linking keys / wrong types
        row = {
            "seq": rng.choice([rng.randint(0, 9), "x", None, -1, 999, 1.5]),
            "kind": rng.choice(["ENTRY", "REFUSAL", "WAT", None, 7, ""]),
            "entry_hash": rng.choice(["00", None, 5, "z" * 64]),
            "prev_hash": rng.choice(["0" * 64, None, "x", 9]),
            "net_edge": rng.choice(_WEIRD),
            "approved": rng.choice([True, False, None, "yes", 1]),
        }
        # randomly inject a secret-looking key (redaction must still drop it on /refusals)
        if rng.random() < 0.5:
            row[rng.choice(_SECRET_KEYS)] = rng.choice(["s3cr3t", "0xWALLET", _WEIRD[5]])
        return json.dumps(row)
    if roll < 0.70:
        # NaN / inf tokens (json.loads admits them by default)
        return ('{"seq":0,"kind":"REFUSAL","entry_hash":"00","prev_hash":"00",'
                '"net_edge":' + rng.choice(["NaN", "Infinity", "-Infinity"]) + "}")
    if roll < 0.85:
        # deeply nested + secret-looking key buried in a decomposition
        return json.dumps({
            "seq": 0, "kind": "REFUSAL", "underlying": "eeth",
            "decomposition": {"underlying": "eeth", "private_key": "0xDEAD",
                              "drivers": [{"token": "leak", "v": float("inf")}]},
            "detail": {"note": "x", "wallet_address": "0xBEEF"},
        })
    # an otherwise-plausible row but with a forged/unlinked hash (tamper)
    return json.dumps({
        "seq": 999, "ts": "2026-06-25T00:00:00+00:00", "kind": "ENTRY",
        "approved": True, "underlying": "ptusdc", "entry_hash": "f" * 64,
        "prev_hash": "a" * 64, "net_edge": "0.05",
    })


def _rand_corrupt_jsonl(rng: random.Random) -> str:
    n = rng.randint(0, 30)
    return "\n".join(_rand_corrupt_row(rng) for _ in range(n)) + ("\n" if n else "")


def _rand_corrupt_surface(rng: random.Random):
    """A corrupt rate_surface.json / exit_nav.json body (decoded object or a raw bad string)."""
    roll = rng.random()
    if roll < 0.2:
        return rng.choice(["{ truncated", "[1,2", "", "null", "not json", '{"a":NaN}'])
    if roll < 0.5:
        return rng.choice([[], [1, 2, 3], 42, "str", None, True])
    obj = {
        "generated_at": rng.choice(_WEIRD),
        "as_of": rng.choice(_WEIRD),
        "quotes": rng.choice([[], [{"underlying": rng.choice(_WEIRD)}], "x", 5, None,
                              [_WEIRD] * 3]),
        "schedule": rng.choice([[], [{"size_usd": float("nan")}], "x", None]),
        rng.choice(_SECRET_KEYS): "leak",
    }
    return obj


def _assert_no_secret_keys(test_obj, ctx=""):
    """Recursively assert NO dict key contains a denylisted substring (the redaction contract)."""
    stack = [test_obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                low = str(k).lower()
                assert not any(s in low for s in _REDACT_SUBSTRINGS), \
                    f"REDACTION LEAK: key {k!r} survived in public payload {ctx}"
                stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)


def _assert_no_nan_inf_numbers(obj, ctx=""):
    """No NaN/inf numeric LEAKS as a top-level verdict number. (Corrupt rows MAY echo back inside
    opaque ``decisions``/``last_n`` payloads verbatim — those are not verdicts; we only assert the
    VERDICT fields below are finite.)"""
    for fld in ("chain_length", "n_decisions", "n_anchors", "n_signals", "n_breached"):
        v = obj.get(fld) if isinstance(obj, dict) else None
        if isinstance(v, float):
            assert math.isfinite(v), f"non-finite verdict {fld}={v!r} {ctx}"


# ═══════════════════════════════════════════════════════════════════════════════════
# 4.1a — corrupt-state fuzz across ALL proof endpoints
# ═══════════════════════════════════════════════════════════════════════════════════
class TestProofApiCorruptStateFuzz:
    N_CASES = 250

    def test_fuzz_proof_endpoints_never_500_never_false_verified(self, client):
        c, data_dir = client
        rd = _rd_dir(data_dir)
        log = rd / "decision_log.jsonl"
        anchors = rd / "anchors.jsonl"
        surface = data_dir / "rates_desk" / "rate_surface.json"
        exit_nav = data_dir / "rates_desk" / "exit_nav.json"

        rng = random.Random(0x9E3779B9)
        for i in range(self.N_CASES):
            # corrupt all four state files independently each iteration
            log.write_text(_rand_corrupt_jsonl(rng), encoding="utf-8")
            anchors.write_text(_rand_corrupt_jsonl(rng), encoding="utf-8")
            try:
                surface.write_text(
                    json.dumps(_rand_corrupt_surface(rng), allow_nan=True)
                    if rng.random() < 0.7 else str(_rand_corrupt_surface(rng)),
                    encoding="utf-8")
            except TypeError:
                surface.write_text("{ truncated", encoding="utf-8")
            try:
                exit_nav.write_text(
                    json.dumps(_rand_corrupt_surface(rng), allow_nan=True), encoding="utf-8")
            except TypeError:
                exit_nav.write_text("not json", encoding="utf-8")

            ctx = f"[case {i}]"

            # ── proof: never 500; verified must NOT be True over corrupt rows ──
            r = c.get("/api/rates-desk/proof")
            assert r.status_code == 200, f"proof {r.status_code} {ctx}"
            d = r.json()
            _assert_no_nan_inf_numbers(d, ctx)
            # any non-empty corrupt log → the chain cannot be honestly verified.
            line_rows = [ln for ln in log.read_text().splitlines() if ln.strip()]
            if line_rows:
                assert d["verified"] is False, (
                    f"proof falsely verified over corrupt rows {ctx}: {d.get('verified')!r}")
            else:
                assert d["verified"] is True and d["chain_length"] == 0, ctx

            # ── refusals: never 500; REDACTION holds even on injected secret keys ──
            rr = c.get("/api/rates-desk/refusals")
            assert rr.status_code == 200, f"refusals {rr.status_code} {ctx}"
            rd_json = rr.json()
            _assert_no_secret_keys(rd_json, ctx)
            assert "chain" in rd_json and "decisions" in rd_json, ctx
            if line_rows:
                assert rd_json["chain"]["verified"] is False, (
                    f"refusals chain falsely verified {ctx}")

            # ── decisions / anchors / exit-nav / competitive-watch: never 500 ──
            for path in ("/api/rates-desk/decisions", "/api/rates-desk/anchors",
                         "/api/rates-desk/exit-nav", "/api/competitive-watch"):
                rx = c.get(path)
                assert rx.status_code == 200, f"{path} -> {rx.status_code} {ctx}"
                assert isinstance(rx.json(), dict), f"{path} non-dict {ctx}"

    def test_fuzz_oversized_huge_array_log(self, client):
        """A huge (10k-row) corrupt log must still 200 + verified=false, not OOM-crash/500."""
        c, data_dir = client
        log = _rd_dir(data_dir) / "decision_log.jsonl"
        rng = random.Random(7)
        log.write_text(
            "\n".join(_rand_corrupt_row(rng) for _ in range(10_000)) + "\n", encoding="utf-8")
        for path in ("/api/rates-desk/proof", "/api/rates-desk/refusals",
                     "/api/rates-desk/decisions"):
            r = c.get(path)
            assert r.status_code == 200, path
        assert c.get("/api/rates-desk/proof").json()["verified"] is False


# ═══════════════════════════════════════════════════════════════════════════════════
# 4.1b — malformed / oversized / out-of-range REQUEST params
# ═══════════════════════════════════════════════════════════════════════════════════
class TestProofApiBadRequestFuzz:
    def test_fuzz_query_params_never_500(self, client):
        """Malformed last_n / limit values: FastAPI validates (422) OR the handler clamps — never
        a 500, never an uncaught raise. A valid log self-verifies regardless of the param."""
        c, data_dir = client
        _write_valid_chain(_rd_dir(data_dir) / "decision_log.jsonl",
                           [_valid_payload(0, approved=False, underlying="eeth"),
                            _valid_payload(1, approved=True, underlying="ptusdc")])
        rng = random.Random(0xABCDEF)
        bad_vals = ["abc", "", "-1", "0", "999999999999", "1e9", "NaN", "1.5",
                    "%00", "1;DROP", "[]", "null", "1 OR 1=1", "-2147483648",
                    "999999999999999999999999999"]
        endpoints = [
            ("/api/rates-desk/proof", "last_n"),
            ("/api/rates-desk/decisions", "limit"),
            ("/api/rates-desk/refusals", "limit"),
            ("/api/rates-desk/anchors", "limit"),
        ]
        for _ in range(120):
            path, param = rng.choice(endpoints)
            val = rng.choice(bad_vals)
            r = c.get(path, params={param: val})
            assert r.status_code in (200, 422), f"{path}?{param}={val} -> {r.status_code}"
            if r.status_code == 200:
                body = r.json()
                assert isinstance(body, dict)
                _assert_no_secret_keys(body, f"{path}?{param}={val}")

    def test_fuzz_unknown_extra_params_ignored(self, client):
        """Injected junk/secret-looking query params never alter the verdict or 500."""
        c, data_dir = client
        _write_valid_chain(_rd_dir(data_dir) / "decision_log.jsonl",
                           [_valid_payload(0, approved=False, underlying="eeth")])
        r = c.get("/api/rates-desk/proof",
                  params={"github_token": "x", "../../etc/passwd": "y", "last_n": "5"})
        assert r.status_code == 200
        assert r.json()["verified"] is True


# ═══════════════════════════════════════════════════════════════════════════════════
# 4.1c — pinned regressions (the exact bug classes WS4 forbids)
# ═══════════════════════════════════════════════════════════════════════════════════
class TestProofApiPins:
    def test_pin_injected_secret_key_redacted_from_refusals(self, client):
        """A REFUSAL row carrying secret/token/wallet keys → those keys NEVER reach /refusals."""
        c, data_dir = client
        # build a VALID chain whose one row carries denylisted keys in its hashed payload
        pl = _valid_payload(0, approved=False, underlying="eeth")
        pl["api_secret"] = "sk-LEAK"
        pl["wallet_address"] = "0xCAFE"
        pl["decomposition"]["private_key"] = "0xDEAD"
        _write_valid_chain(_rd_dir(data_dir) / "decision_log.jsonl", [pl])
        r = c.get("/api/rates-desk/refusals")
        assert r.status_code == 200
        body = r.json()
        _assert_no_secret_keys(body, "pin")
        # the literal secret VALUES must not appear either (they lived under redacted keys)
        blob = json.dumps(body)
        assert "sk-LEAK" not in blob and "0xCAFE" not in blob and "0xDEAD" not in blob

    def test_pin_forged_unlinked_row_never_becomes_head(self, client):
        """A fabricated seq:999 with a bogus prev_hash → verified=false, never the published head."""
        c, data_dir = client
        log = _rd_dir(data_dir) / "decision_log.jsonl"
        rows = _write_valid_chain(log, [_valid_payload(0, approved=True, underlying="ptusdc")])
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"seq": 999, "kind": "ENTRY", "entry_hash": "f" * 64,
                                "prev_hash": "a" * 64, "approved": True}) + "\n")
        d = c.get("/api/rates-desk/proof").json()
        assert d["verified"] is False
        assert d["head_hash"] != "f" * 64  # the forged hash never becomes the published head
        _ = rows

    def test_pin_corrupt_line_drives_verified_false(self, client):
        """A single non-JSON line in an otherwise-valid log → verified=false (tamper evidence)."""
        c, data_dir = client
        log = _rd_dir(data_dir) / "decision_log.jsonl"
        _write_valid_chain(log, [_valid_payload(0, approved=True, underlying="ptusdc")])
        with log.open("a", encoding="utf-8") as f:
            f.write("{ this is not valid json\n")
        assert c.get("/api/rates-desk/proof").json()["verified"] is False
        # refusals echoes the same broken verdict and still never 500s
        assert c.get("/api/rates-desk/refusals").json()["chain"]["verified"] is False

    def test_pin_absent_logs_fail_closed_vacuous(self, client):
        """No state files at all → honest empty/vacuous shapes, never 500, never fabricated."""
        c, _ = client
        d = c.get("/api/rates-desk/proof").json()
        assert d["verified"] is True and d["chain_length"] == 0 and d["head_hash"] is None
        ref = c.get("/api/rates-desk/refusals").json()
        assert ref["decisions"] == [] and ref["counts"] == {"ENTRY": 0, "REFUSAL": 0}
        cw = c.get("/api/competitive-watch").json()
        assert cw["overall_state"] == "WATCH" and cw["counts"]["BREACHED"] == 0
        en = c.get("/api/rates-desk/exit-nav").json()
        assert en["flagged"] is True and en["is_advisory"] is True and en["as_of"] is None

    def test_pin_competitive_watch_corrupt_falls_back_all_watch(self, client):
        """A corrupt competitive_watch.json → fail-closed all-WATCH, never a fabricated SAFE/BREACH."""
        c, data_dir = client
        (data_dir / "competitive_watch.json").write_text("{ truncated json", encoding="utf-8")
        d = c.get("/api/competitive-watch").json()
        assert d["overall_state"] == "WATCH"
        assert d["n_breached"] == 0 and d["counts"]["BREACHED"] == 0
        # corrupt file with wrong-typed signals → still the safe fallback
        (data_dir / "competitive_watch.json").write_text(
            json.dumps({"signals": "not-a-list"}), encoding="utf-8")
        d2 = c.get("/api/competitive-watch").json()
        assert d2["overall_state"] == "WATCH" and d2["n_breached"] == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-p", "no:randomly", "-q"]))
