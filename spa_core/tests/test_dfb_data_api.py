"""test_dfb_data_api.py — the DFB Data API (Month-3 Lane-1) key-gated developer surface.

Verifies the risk-graded ``/api/dfb/v1/*`` Data API end-to-end against a HERMETIC
universe fixture (the SAME shared contract test_api_dfb.py uses). Three lenses per the
charter:

  • PROPERTY  — flag OFF → the WHOLE /v1 surface 404s; the v1 data is BYTE-IDENTICAL to
    the public /api/dfb/pools overlay (no-fork, no divergent grade); the refused feed
    contains exactly the REFUSE-verdict pools.
  • RED-TEAM  — flag OFF = total 404 (no leak); flag ON + NO key configured → 401
    (fail-CLOSED, never silently open); a spoofed/wrong key → 401; a flood trips the
    per-key rate limit (429).
  • SMOKE     — flag ON + valid key → /v1/pools serves the graded universe; /v1/refusals
    serves the refused feed; /v1/screener filters; flag OFF → 404.

The auth core (api_security / auth.py) reads SPA_API_KEY from env → Keychain. We set the
env key under monkeypatch and reset the auth singleton so the configured-key state is
hermetic.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SPA_CORE = _HERE.parent
_PROJECT_ROOT = _SPA_CORE.parent
for _p in [str(_SPA_CORE), str(_PROJECT_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest

pytest.importorskip(
    "fastapi", reason="fastapi optional dep not installed — API suite skipped"
)
from fastapi.testclient import TestClient  # noqa: E402

import spa_core.api.server as server  # noqa: E402
from spa_core.api.routers import dfb_data_api  # noqa: E402

GENESIS_PREV = "0" * 64
_TEST_KEY = "dfb-data-api-test-key-0123456789"


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _pool_obj(pool_id: str, *, risk_class="B", verdict="ALLOW", tail_veto=False,
              chain="ethereum", protocol="aave_v3") -> dict:
    return {
        "pool_id": pool_id, "protocol": protocol, "chain": chain, "asset": "USDC",
        "tier": "T1", "apy": {"total": 4.2, "base": 3.8, "reward": 0.4},
        "tvl_usd": 1_200_000_000.0, "risk_class": risk_class,
        "structural_haircut": 0.02, "total_haircut": 0.05,
        "exit_liquidity": [
            {"ticket_usd": 1_000_000, "absorbable_usd": 950_000.0,
             "dex_exit_frac": 0.95, "flagged": False}],
        "refusal": {"verdict": verdict,
                    "reason": ("structural_tail" if verdict == "REFUSE" else None),
                    "tail_veto": tail_veto},
        "as_of": "2026-06-30T00:00:00+00:00", "data_source": "defillama_feed",
        "feed_coverage": "full", "prev_hash": GENESIS_PREV, "row_hash": "deadbeef" * 8,
    }


def _write_universe(data_dir: Path, pools: list) -> None:
    dfb = data_dir / "dfb"
    (dfb / "pool").mkdir(parents=True, exist_ok=True)
    (dfb / "pools.json").write_text(_canonical(pools), encoding="utf-8")
    for p in pools:
        (dfb / "pool" / f"{p['pool_id']}.json").write_text(_canonical(p), encoding="utf-8")


_POOLS = [
    _pool_obj("dfb_pool_a", risk_class="A", verdict="ALLOW", chain="ethereum"),
    _pool_obj("dfb_pool_toxic", risk_class="D", verdict="REFUSE", tail_veto=True,
              chain="arbitrum", protocol="some_lrt"),
    _pool_obj("dfb_pool_c", risk_class="C", verdict="WATCH", chain="ethereum"),
]


def _configure_key(monkeypatch, key: str | None) -> None:
    """Set (or clear) SPA_API_KEY and reset the auth singleton so has_key() reflects it."""
    import spa_core.api.auth as auth_mod
    if key is None:
        monkeypatch.delenv("SPA_API_KEY", raising=False)
    else:
        monkeypatch.setenv("SPA_API_KEY", key)
    auth_mod._auth_instance = None  # force reload of the key on next get_auth()


@pytest.fixture()
def flag_on_client(tmp_path, monkeypatch):
    """Flag ON, key configured, hermetic universe. Yields (client, key)."""
    _write_universe(tmp_path, _POOLS)
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    monkeypatch.setenv("SPA_DFB_DATA_API", "1")
    _configure_key(monkeypatch, _TEST_KEY)
    dfb_data_api._reset_rate_stores()
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c, _TEST_KEY
    dfb_data_api._reset_rate_stores()


@pytest.fixture()
def flag_off_client(tmp_path, monkeypatch):
    """Flag OFF (default). Every /v1 path must 404."""
    _write_universe(tmp_path, _POOLS)
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    monkeypatch.delenv("SPA_DFB_DATA_API", raising=False)
    _configure_key(monkeypatch, _TEST_KEY)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c


def _hdr(key: str) -> dict:
    return {"X-API-Key": key}


# ══════════════════════════════════════════════════════════════════════════════
# RED-TEAM — flag OFF = total 404 (no leak)
# ══════════════════════════════════════════════════════════════════════════════
_V1_PATHS = [
    "/api/dfb/v1",
    "/api/dfb/v1/pools",
    "/api/dfb/v1/pool/dfb_pool_a",
    "/api/dfb/v1/pool/dfb_pool_a/history",
    "/api/dfb/v1/refusals",
    "/api/dfb/v1/screener",
]


def test_redteam_flag_off_total_404(flag_off_client):
    """Flag OFF → EVERY /v1 path is 404 even WITH a valid key (no surface leak)."""
    for path in _V1_PATHS:
        r = flag_off_client.get(path, headers=_hdr(_TEST_KEY))
        assert r.status_code == 404, f"{path} leaked when flag OFF: {r.status_code}"


# ══════════════════════════════════════════════════════════════════════════════
# RED-TEAM — fail-CLOSED auth: no key configured → 401, never open
# ══════════════════════════════════════════════════════════════════════════════
def test_redteam_flag_on_no_key_configured_401(tmp_path, monkeypatch):
    """Flag ON but the server has NO key configured → 401 (never silently open)."""
    _write_universe(tmp_path, _POOLS)
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    monkeypatch.setenv("SPA_DFB_DATA_API", "1")
    _configure_key(monkeypatch, None)  # no key
    # Also neutralize any real Keychain key so has_key() is deterministically False.
    monkeypatch.setattr("spa_core.api.auth.APIAuth._load_key", lambda self: None)
    import spa_core.api.auth as auth_mod
    auth_mod._auth_instance = None
    dfb_data_api._reset_rate_stores()
    with TestClient(server.app, raise_server_exceptions=True) as c:
        r = c.get("/api/dfb/v1/pools")  # no creds either
        assert r.status_code == 401
        assert "configured" in json.dumps(r.json()).lower()


def test_redteam_missing_credential_401(flag_on_client):
    """Flag ON + key configured, but the REQUEST sends no key → 401."""
    client, _ = flag_on_client
    r = client.get("/api/dfb/v1/pools")
    assert r.status_code == 401


def test_redteam_spoofed_key_401(flag_on_client):
    """A wrong / spoofed / rotated key → 401 (constant-time reject, no leak)."""
    client, _ = flag_on_client
    r = client.get("/api/dfb/v1/pools", headers=_hdr("totally-wrong-key"))
    assert r.status_code == 401
    # also a forged bearer
    r2 = client.get("/api/dfb/v1/pools",
                    headers={"Authorization": "Bearer 9999999999.deadbeef"})
    assert r2.status_code == 401


def test_redteam_rate_limit_fires_on_flood(tmp_path, monkeypatch):
    """A flood from ONE key trips the per-key (free-tier) rate limit → 429."""
    _write_universe(tmp_path, _POOLS)
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    monkeypatch.setenv("SPA_DFB_DATA_API", "1")
    monkeypatch.setenv("SPA_DFB_API_FREE_PER_MIN", "5")  # tiny bucket for the test
    # Disable the app-wide per-IP middleware so we isolate the PER-KEY limiter.
    monkeypatch.setenv("SPA_RATE_LIMIT_ENABLED", "0")
    _configure_key(monkeypatch, _TEST_KEY)
    # Re-import limits: the module read the env at import → force a fresh store with new cap.
    import importlib
    importlib.reload(dfb_data_api)
    # the reloaded module rebinds router; re-include is not needed for direct-call, but the
    # TestClient uses the app's already-registered router object. Patch the live router's store.
    dfb_data_api._reset_rate_stores()
    # Patch the FREE cap on the live (already-mounted) module the app actually calls.
    live_mod = sys.modules["spa_core.api.routers.dfb_data_api"]
    live_mod._FREE_PER_MIN = 5
    live_mod._reset_rate_stores()
    with TestClient(server.app, raise_server_exceptions=True) as c:
        codes = [c.get("/api/dfb/v1/pools", headers=_hdr(_TEST_KEY)).status_code
                 for _ in range(12)]
    assert 429 in codes, f"rate limit never fired: {codes}"
    assert codes.count(200) <= 6, f"too many 200s — bucket not enforced: {codes}"


# ══════════════════════════════════════════════════════════════════════════════
# RED-TEAM / PROPERTY — no-fork: v1 data byte-identical to the public overlay
# ══════════════════════════════════════════════════════════════════════════════
def test_property_v1_pools_byte_identical_to_public_overlay(flag_on_client):
    """The v1 graded universe is the SAME rows the public /api/dfb/pools serves
    (no-fork, no divergent grade) — pool-for-pool, field-for-field on the overlay."""
    client, key = flag_on_client
    public = client.get("/api/dfb/pools").json()["pools"]
    v1 = client.get("/api/dfb/v1/pools", headers=_hdr(key)).json()["pools"]
    assert _canonical(v1) == _canonical(public)


# ══════════════════════════════════════════════════════════════════════════════
# SMOKE — flag ON + key → the surface serves the graded universe + refused feed
# ══════════════════════════════════════════════════════════════════════════════
def test_smoke_pools_served(flag_on_client):
    client, key = flag_on_client
    r = client.get("/api/dfb/v1/pools", headers=_hdr(key))
    assert r.status_code == 200
    body = r.json()
    assert body["api_version"] == "v1"
    assert body["is_advisory"] is True
    assert body["n_pools"] == 3
    assert "key" in body and len(body["key"]) == 16  # fingerprint, not the raw key
    assert _TEST_KEY not in json.dumps(body)  # raw key never echoed


def test_smoke_refusals_feed(flag_on_client):
    """The refused-pools feed contains exactly the REFUSE-verdict pools (the differentiator)."""
    client, key = flag_on_client
    body = client.get("/api/dfb/v1/refusals", headers=_hdr(key)).json()
    assert body["n_refused"] == 1
    ids = {r["pool_id"] for r in body["refusals"]}
    assert ids == {"dfb_pool_toxic"}
    assert body["refusals"][0]["refusal"]["tail_veto"] is True


def test_smoke_screener_filters(flag_on_client):
    client, key = flag_on_client
    # by risk_class
    d = client.get("/api/dfb/v1/screener?risk_class=D", headers=_hdr(key)).json()
    assert d["n_matched"] == 1 and d["pools"][0]["pool_id"] == "dfb_pool_toxic"
    # refused=true
    ref = client.get("/api/dfb/v1/screener?refused=true", headers=_hdr(key)).json()
    assert {p["pool_id"] for p in ref["pools"]} == {"dfb_pool_toxic"}
    # by chain
    eth = client.get("/api/dfb/v1/screener?chain=ethereum", headers=_hdr(key)).json()
    assert {p["pool_id"] for p in eth["pools"]} == {"dfb_pool_a", "dfb_pool_c"}
    # refused=false excludes the toxic pool
    notref = client.get("/api/dfb/v1/screener?refused=false", headers=_hdr(key)).json()
    assert "dfb_pool_toxic" not in {p["pool_id"] for p in notref["pools"]}


def test_smoke_pool_detail_and_404(flag_on_client):
    client, key = flag_on_client
    ok = client.get("/api/dfb/v1/pool/dfb_pool_a", headers=_hdr(key))
    assert ok.status_code == 200 and ok.json()["pool_id"] == "dfb_pool_a"
    # unknown id → 404 (a guess is a lie)
    miss = client.get("/api/dfb/v1/pool/nope_not_real", headers=_hdr(key))
    assert miss.status_code == 404
    # path-traversal id → 404
    bad = client.get("/api/dfb/v1/pool/..%2f..%2fsecret", headers=_hdr(key))
    assert bad.status_code in (404, 400)


def test_smoke_index_self_describes(flag_on_client):
    client, key = flag_on_client
    body = client.get("/api/dfb/v1", headers=_hdr(key)).json()
    assert body["product"] == "DFB Data API"
    assert "owner_gated_launch" in body
    assert "GET /api/dfb/v1/refusals" in body["endpoints"]


def test_smoke_bearer_token_accepted(flag_on_client):
    """The HMAC bearer token (not just the raw key) is accepted."""
    client, key = flag_on_client
    from spa_core.api.auth import get_auth
    token = get_auth().generate_token()
    r = client.get("/api/dfb/v1/pools", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
