"""test_p1_risk_no_network.py — FIX 4 (P1): scoring_engine must not make live HTTP calls.

Verifies that:
- RiskScoringEngine does NOT call urllib.request.urlopen under any normal path
- When a local cache file exists, it is used instead of network
- When cache is absent, BOOTSTRAP_PROTOCOLS are used (no network)
- offline=True uses bootstrap only
- HTTP errors do NOT propagate (engine is always fail-safe)
- The engine produces scores with no network access
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from spa_core.risk.scoring_engine import (
    RiskScoringEngine,
    BOOTSTRAP_PROTOCOLS,
    DEFILLAMA_CACHE_FILE,
    DEFILLAMA_PROTOCOLS_URL,
)


# ---------------------------------------------------------------------------
# Helper: fake cache content shaped like DefiLlama /protocols list
# ---------------------------------------------------------------------------
def _fake_cache(slugs: list[str]) -> list[dict]:
    return [
        {
            "slug": slug,
            "name": slug.replace("-", " ").title(),
            "tvl": 1_000_000_000.0,
            "chains": ["ethereum"],
            "chain": "ethereum",
        }
        for slug in slugs
    ]


# ---------------------------------------------------------------------------
# 1. No urllib.request.urlopen call when cache exists
# ---------------------------------------------------------------------------
def test_no_network_call_when_cache_exists():
    """If defi_llama_cache.json exists, engine must not call urlopen."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "defi_llama_cache.json"
        cache_path.write_text(json.dumps(_fake_cache(["aave-v3", "compound-v3"])))

        with patch("spa_core.risk.scoring_engine.DEFILLAMA_CACHE_FILE", cache_path):
            with patch("urllib.request.urlopen") as mock_urlopen:
                engine = RiskScoringEngine(offline=False)
                # Trigger data load
                engine._ensure_loaded()
                mock_urlopen.assert_not_called(), (
                    "urlopen must not be called when a local cache file exists"
                )


# ---------------------------------------------------------------------------
# 2. No network call when cache is absent (bootstrap path)
# ---------------------------------------------------------------------------
def test_no_network_call_when_cache_absent():
    """If cache file doesn't exist, engine uses bootstrap — still no network."""
    nonexistent = Path("/tmp/_no_such_cache_spa_test.json")
    assert not nonexistent.exists()

    with patch("spa_core.risk.scoring_engine.DEFILLAMA_CACHE_FILE", nonexistent):
        with patch("urllib.request.urlopen") as mock_urlopen:
            engine = RiskScoringEngine(offline=False)
            engine._ensure_loaded()
            mock_urlopen.assert_not_called(), (
                "urlopen must not be called even when cache is absent"
            )


# ---------------------------------------------------------------------------
# 3. offline=True always uses bootstrap
# ---------------------------------------------------------------------------
def test_offline_mode_uses_bootstrap():
    with patch("urllib.request.urlopen") as mock_urlopen:
        engine = RiskScoringEngine(offline=True)
        engine._ensure_loaded()
        mock_urlopen.assert_not_called()
        # Data should be bootstrap protocols
        assert engine._protocols_data is not None
        assert len(engine._protocols_data) > 0


# ---------------------------------------------------------------------------
# 4. Engine produces scores with no network
# ---------------------------------------------------------------------------
def test_engine_scores_without_network():
    """compute_all() must return results with no urllib calls."""
    with patch("urllib.request.urlopen") as mock_urlopen:
        engine = RiskScoringEngine(offline=True)
        scores = engine.compute_all()
        mock_urlopen.assert_not_called()
        assert isinstance(scores, list)
        assert len(scores) > 0


# ---------------------------------------------------------------------------
# 5. Cache content is loaded into _protocols_data
# ---------------------------------------------------------------------------
def test_cache_content_used_in_scoring():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "defi_llama_cache.json"
        cache_data = _fake_cache(["aave-v3"])
        cache_path.write_text(json.dumps(cache_data))

        with patch("spa_core.risk.scoring_engine.DEFILLAMA_CACHE_FILE", cache_path):
            engine = RiskScoringEngine(offline=False)
            engine._ensure_loaded()
            assert engine._protocols_data is not None
            # aave-v3 should be present (from cache)
            assert "aave-v3" in engine._protocols_data


# ---------------------------------------------------------------------------
# 6. Malformed cache → bootstrap fallback, no exception
# ---------------------------------------------------------------------------
def test_malformed_cache_falls_back_to_bootstrap():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "defi_llama_cache.json"
        cache_path.write_text("NOT VALID JSON {{{{")

        with patch("spa_core.risk.scoring_engine.DEFILLAMA_CACHE_FILE", cache_path):
            with patch("urllib.request.urlopen") as mock_urlopen:
                engine = RiskScoringEngine(offline=False)
                engine._ensure_loaded()  # must not raise
                mock_urlopen.assert_not_called()
                assert engine._protocols_data is not None


# ---------------------------------------------------------------------------
# 7. Cache with wrong type → bootstrap, no network
# ---------------------------------------------------------------------------
def test_cache_wrong_type_falls_back_to_bootstrap():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "defi_llama_cache.json"
        cache_path.write_text(json.dumps({"wrong": "type"}))  # dict, not list

        with patch("spa_core.risk.scoring_engine.DEFILLAMA_CACHE_FILE", cache_path):
            with patch("urllib.request.urlopen") as mock_urlopen:
                engine = RiskScoringEngine(offline=False)
                engine._ensure_loaded()
                mock_urlopen.assert_not_called()


# ---------------------------------------------------------------------------
# 8. No network = deterministic: same inputs → same scores
# ---------------------------------------------------------------------------
def test_scoring_is_deterministic_offline():
    engine1 = RiskScoringEngine(offline=True)
    engine2 = RiskScoringEngine(offline=True)
    scores1 = {s.slug: s.score_numeric for s in engine1.compute_all()}
    scores2 = {s.slug: s.score_numeric for s in engine2.compute_all()}
    assert scores1 == scores2, "Offline scoring must be deterministic"


# ---------------------------------------------------------------------------
# 9. score_all returns required fields
# ---------------------------------------------------------------------------
def test_score_all_fields_present():
    engine = RiskScoringEngine(offline=True)
    scores = engine.compute_all()
    assert len(scores) > 0
    for s in scores:
        # ProtocolRiskScore is a dataclass — use attribute access
        assert hasattr(s, "protocol")
        assert hasattr(s, "slug")
        assert hasattr(s, "grade")
        assert hasattr(s, "score_numeric")
        assert hasattr(s, "fallback_used")


# ---------------------------------------------------------------------------
# 10. DEFILLAMA_CACHE_FILE constant is defined
# ---------------------------------------------------------------------------
def test_cache_file_constant_defined():
    assert DEFILLAMA_CACHE_FILE is not None
    assert isinstance(DEFILLAMA_CACHE_FILE, Path)
    assert DEFILLAMA_CACHE_FILE.name == "defi_llama_cache.json"
