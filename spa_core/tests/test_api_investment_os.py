"""Pin the /api/investment-os surface — read-only, verbatim, fail-CLOSED product-layer analyst artifacts.

Direct-call unit tests (no ASGI lifespan): monkeypatch the data dir, write an analyst artifact, assert the
router serves it verbatim + advisory-stamped, and that a missing artifact yields an honest "unavailable"
envelope (never a 500, never a fabricated number). Deterministic; no network.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json

from spa_core.api import server as SRV
from spa_core.api.routers import investment_os as IO


def _seed(tmp_path, slug_file, payload):
    d = tmp_path / "investment_os"
    d.mkdir(parents=True, exist_ok=True)
    (d / slug_file).write_text(json.dumps(payload), encoding="utf-8")


def test_available_artifact_served_verbatim(monkeypatch, tmp_path):
    monkeypatch.setattr(SRV, "_DATA_DIR", tmp_path)
    _seed(tmp_path, "stablecoin_yield.json",
          {"agent": "stablecoin_yield", "status": "ok", "is_advisory": True,
           "top_stablecoin_yields": [{"value": {"protocol": "aave_usdc"}}]})
    out = IO.stablecoin_yield()
    assert out["available"] is True
    assert out["agent"] == "stablecoin_yield"
    assert out["is_advisory"] is True
    assert out["top_stablecoin_yields"][0]["value"]["protocol"] == "aave_usdc"
    assert "ADVISORY" in out["note"]


def test_missing_artifact_is_honest_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(SRV, "_DATA_DIR", tmp_path)  # nothing seeded
    out = IO.market_regime()
    assert out["available"] is False
    assert out["is_advisory"] is True
    assert out["live_eligible"] is False
    assert "not produced yet" in out["unavailable_reason"]


def test_index_lists_all_with_availability(monkeypatch, tmp_path):
    monkeypatch.setattr(SRV, "_DATA_DIR", tmp_path)
    _seed(tmp_path, "reporting.json", {"agent": "reporting", "status": "ok"})
    out = IO.index()
    assert out["count"] == 3
    by_slug = {a["slug"]: a for a in out["analysts"]}
    assert set(by_slug) == {"stablecoin-yield", "market-regime", "reporting"}
    assert by_slug["reporting"]["available"] is True
    assert by_slug["stablecoin-yield"]["available"] is False
    assert by_slug["market-regime"]["endpoint"] == "/api/investment-os/market-regime"


def test_never_500_on_garbage(monkeypatch, tmp_path):
    monkeypatch.setattr(SRV, "_DATA_DIR", tmp_path)
    d = tmp_path / "investment_os"; d.mkdir(parents=True)
    (d / "reporting.json").write_text("{ not json", encoding="utf-8")  # corrupt → treated as missing
    out = IO.reporting()
    assert out["available"] is False and out["is_advisory"] is True
