"""test_api_btc_engine.py — /api/btc-engine/* contract (owner decision 2026-09-08, earn-defi D-52).

Properties:
  1. read-only pass-through of the four JSON files produced by the earn-defi daily job;
  2. fail-CLOSED and honest: missing file → 200 {status: no_data}, corrupt → 503 {status: no_data},
     never a 500, never a fabricated number;
  3. the origin label in the data is passed through untouched (paper/shadow never relabelled);
  4. only the fixed catalogue is reachable — no path parameter touches the filesystem.

Hermetic: SPA_BTC_ENGINE_SITE_DIR points at tmp_path.
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

pytest.importorskip("fastapi", reason="fastapi optional dep not installed — API suite skipped")
from fastapi.testclient import TestClient  # noqa: E402

import spa_core.api.server as server  # noqa: E402
from spa_core.api.routers import btc_engine  # noqa: E402

FILES = ["track", "commitments", "runway", "shadow"]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SPA_BTC_ENGINE_SITE_DIR", str(tmp_path))
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c, tmp_path


def test_missing_files_are_honest_no_data_not_500(client):
    c, _ = client
    for name in FILES:
        r = c.get(f"/api/btc-engine/{name}.json")
        assert r.status_code == 200, name
        body = r.json()
        assert body["status"] == "no_data" and body["reason"] == "file_missing"
        assert "nav_usdt" not in json.dumps(body)  # nothing fabricated
        assert r.headers.get("cache-control", "").startswith("no-")
    idx = c.get("/api/btc-engine").json()
    assert set(idx["files"]) == set(FILES) and not any(v["present"] for v in idx["files"].values())


def test_passthrough_keeps_origin_and_numbers_verbatim(client):
    c, d = client
    track = {"origin": "paper", "days": 5, "start_date": "2026-09-02", "latest": {"date": "2026-09-06", "nav_usdt": 102636.99, "cum_return": 0.02637},
             "series": [{"date": "2026-09-06", "nav_usdt": 102636.99, "drawdown": -0.0078, "btc_weight": 0.6843, "backfilled": False}], "chain_head": "abc"}
    (d / "track.json").write_text(json.dumps(track))
    (d / "commitments.json").write_text(json.dumps([{"date": "2026-09-03", "commitment_hash": "24195c", "package": {"regime": "NEUTRAL"}}]))
    (d / "shadow.json").write_text(json.dumps({"date": "2026-09-06", "config_version": "0.4", "gap_pct": 0.0, "shadow": {"nav_usdt": 102636.99, "regime": "NEUTRAL", "weight": 0.68}, "live": {}}))
    r = c.get("/api/btc-engine/track.json"); body = r.json()
    assert r.status_code == 200
    assert body["origin"] == "paper" and body["latest"]["nav_usdt"] == 102636.99 and body["series"][0]["btc_weight"] == 0.6843
    assert "_fetched_at" in body and body["_file_mtime"] is not None
    r = c.get("/api/btc-engine/commitments.json"); body = r.json()
    assert body["data"][0]["commitment_hash"] == "24195c"  # a list is wrapped, not reshaped
    r = c.get("/api/btc-engine/shadow.json"); assert r.json()["config_version"] == "0.4"
    idx = c.get("/api/btc-engine").json()
    assert idx["files"]["track"]["present"] is True and idx["files"]["runway"]["present"] is False


def test_corrupt_or_oversized_file_is_503_no_data_never_500(client, monkeypatch):
    c, d = client
    (d / "runway.json").write_text("{not json")
    r = c.get("/api/btc-engine/runway.json")
    assert r.status_code == 503 and r.json()["status"] == "no_data" and r.json()["reason"] == "unreadable"
    monkeypatch.setattr(btc_engine, "MAX_BYTES", 5)
    (d / "track.json").write_text(json.dumps({"origin": "paper", "series": []}))
    r = c.get("/api/btc-engine/track.json")
    assert r.status_code == 503 and r.json()["reason"] == "file_too_large"


def test_only_the_fixed_catalogue_is_reachable(client):
    c, d = client
    (d / "secret.json").write_text("{}")
    for path in ("/api/btc-engine/secret.json", "/api/btc-engine/../track.json", "/api/btc-engine/track.json/../secret.json"):
        r = c.get(path)
        assert r.status_code in (404, 200)
        if r.status_code == 200:
            assert r.json().get("status") == "no_data" or "secret" not in r.text


def test_default_site_dir_is_the_earn_defi_repo(monkeypatch):
    monkeypatch.delenv("SPA_BTC_ENGINE_SITE_DIR", raising=False)
    assert btc_engine.site_dir().as_posix().endswith("Documents/earn-defi/site")
