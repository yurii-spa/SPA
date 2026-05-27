"""
Tests for spa_core/risk/scoring_engine.py (FEAT-RISK-001).

Deterministic, fully offline — every network call is patched, every file
read uses ``tmp_path``. Coverage matches the design checklist:

* Bootstrap path works without network.
* Each of the 15 subscore methods is checked on boundary values (0, mid, 1).
* Grade mapping (A/B/C/D) tested exactly on the 0.85/0.70/0.55 thresholds.
* Missing incidents/audit files degrade gracefully (neutral 0.5,
  ``fallback_used=True``).
* ``compute_all`` returns one record per whitelist slug.
* JSON export round-trip + dry-run + correct schema.
* Determinism: two consecutive ``compute_all`` calls produce identical output
  (excluding the ``generated_at`` timestamp).
* Weights are normalised to 1.0.
* DefiLlama fetch is mocked for success and timeout cases.

No data/ directory mutation occurs — all writes are to ``tmp_path``.
"""

from __future__ import annotations

import json
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from risk import scoring_engine as se


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def offline_engine(tmp_path):
    """Engine that never touches the network and has no incident/audit data."""
    return se.RiskScoringEngine(
        protocols_file=tmp_path / "protocols.json",
        incidents_file=tmp_path / "incidents.json",
        audit_file=tmp_path / "audit_findings.json",
        offline=True,
    )


@pytest.fixture
def incidents_file(tmp_path):
    """Minimal valid incidents.json with one Curve incident."""
    p = tmp_path / "incidents.json"
    data = {
        "updated_at": "2026-05-27T00:00:00Z",
        "by_protocol_summary": {
            "curve":   {"incidents": 1, "total_lost_usd": 73_500_000.0, "last_incident": "2023-07-30"},
            "euler":   {"incidents": 1, "total_lost_usd": 197_000_000.0, "last_incident": "2023-03-13"},
            "aave-v3": {"incidents": 0, "total_lost_usd": 0.0, "last_incident": None},
        },
    }
    p.write_text(json.dumps(data))
    return p


@pytest.fixture
def audit_file(tmp_path):
    """Minimal valid audit_findings.json."""
    p = tmp_path / "audit_findings.json"
    data = {
        "by_protocol": {
            "aave-v3":  {"critical": 0, "high": 1, "medium": 3, "low": 10},
            "curve":    {"critical": 1, "high": 2, "medium": 5, "low": 7},
        },
    }
    p.write_text(json.dumps(data))
    return p


@pytest.fixture
def engine_with_data(tmp_path, incidents_file, audit_file):
    return se.RiskScoringEngine(
        protocols_file=tmp_path / "protocols.json",
        incidents_file=incidents_file,
        audit_file=audit_file,
        offline=True,
    )


# ─── 1. Module-level invariants ───────────────────────────────────────────────

def test_weights_normalised_to_one():
    total = sum(se.WEIGHTS.values())
    assert abs(total - 1.0) < 1e-9


def test_weights_contain_all_15_keys():
    expected_keys = {
        "tvl_magnitude", "tvl_trend", "protocol_age", "hack_history",
        "audit_count", "audit_findings_severity", "yield_source_type",
        "oracle_risk", "bridge_dependency", "timelock_duration",
        "multisig_threshold", "liquidity_depth", "cross_protocol_deps",
        "regulatory_surface", "chain_maturity",
    }
    assert set(se.WEIGHTS.keys()) == expected_keys


def test_boosted_subscores_have_higher_weight():
    # Critical subscores (oracle_risk, hack_history, audit_findings_severity,
    # timelock_duration) carry a 1.5x raw multiplier — so post-normalisation
    # they should still be strictly larger than baseline subscores.
    baseline = se.WEIGHTS["tvl_magnitude"]
    for key in ("oracle_risk", "hack_history", "audit_findings_severity",
                "timelock_duration"):
        assert se.WEIGHTS[key] > baseline


def test_bootstrap_covers_all_whitelist():
    for slug in se.SPA_WHITELIST:
        assert slug in se.BOOTSTRAP_PROTOCOLS, f"missing bootstrap entry: {slug}"


# ─── 2. Grade mapping (boundaries) ────────────────────────────────────────────

@pytest.mark.parametrize("score,expected", [
    (1.00, "A"),
    (0.85, "A"),       # exact A boundary
    (0.8499999, "B"),  # just below A
    (0.70, "B"),       # exact B boundary
    (0.6999999, "C"),  # just below B
    (0.55, "C"),       # exact C boundary
    (0.5499999, "D"),  # just below C
    (0.00, "D"),
])
def test_grade_for_score_boundaries(score, expected):
    assert se.grade_for_score(score) == expected


# ─── 3. _clip helper ──────────────────────────────────────────────────────────

def test_clip_low():
    assert se._clip(-0.5) == 0.0


def test_clip_high():
    assert se._clip(1.5) == 1.0


def test_clip_in_range():
    assert se._clip(0.42) == 0.42


# ─── 4. Each of 15 subscore methods on boundary values ────────────────────────

def test_score_tvl_magnitude_zero(offline_engine):
    assert offline_engine._score_tvl_magnitude({"tvl_usd": 0.0}) == 0.0


def test_score_tvl_magnitude_max(offline_engine):
    assert offline_engine._score_tvl_magnitude({"tvl_usd": 5_000_000_000.0}) == 1.0


def test_score_tvl_magnitude_mid(offline_engine):
    s = offline_engine._score_tvl_magnitude({"tvl_usd": 250_000_000.0})
    assert 0.4 < s < 0.7  # log10 of 250M is between 50M and 1B


def test_score_tvl_trend_negative(offline_engine):
    assert offline_engine._score_tvl_trend({"tvl_change_30d_pct": -50.0}) == 0.0


def test_score_tvl_trend_zero(offline_engine):
    assert offline_engine._score_tvl_trend({"tvl_change_30d_pct": 0.0}) == 0.5


def test_score_tvl_trend_positive(offline_engine):
    assert offline_engine._score_tvl_trend({"tvl_change_30d_pct": 50.0}) == 1.0


def test_score_protocol_age_old(offline_engine):
    assert offline_engine._score_protocol_age({"launched_year": 2017}) == 1.0


def test_score_protocol_age_young(offline_engine):
    # Current year (2026) launched this year — age 0 → 0.0
    assert offline_engine._score_protocol_age({"launched_year": 2026}) == 0.0


def test_score_protocol_age_mid(offline_engine):
    s = offline_engine._score_protocol_age({"launched_year": 2024})
    assert 0.0 < s < 1.0


def test_score_hack_history_no_data(offline_engine):
    # No incidents.json → neutral 0.5
    assert offline_engine._score_hack_history({}, "aave-v3") == 0.5


def test_score_hack_history_clean(engine_with_data):
    engine_with_data._ensure_loaded()
    # aave-v3 has zero incidents in fixture
    assert engine_with_data._score_hack_history({}, "aave-v3") == 1.0


def test_score_hack_history_penalty(engine_with_data):
    engine_with_data._ensure_loaded()
    # curve: 1 incident + $73.5M → score = 1 - 0.20 - 0.15*0.0735 ≈ 0.789
    s = engine_with_data._score_hack_history({}, "curve")
    assert 0.7 < s < 0.85


def test_score_audit_count_zero(offline_engine):
    assert offline_engine._score_audit_count({"audit_count": 0}) == 0.0


def test_score_audit_count_max(offline_engine):
    assert offline_engine._score_audit_count({"audit_count": 8}) == 1.0


def test_score_audit_count_mid(offline_engine):
    assert offline_engine._score_audit_count({"audit_count": 3}) == 0.5


def test_score_audit_findings_severity_missing(offline_engine):
    # No audit file → neutral 0.5
    assert offline_engine._score_audit_findings_severity({}, "aave-v3") == 0.5


def test_score_audit_findings_severity_clean(engine_with_data):
    engine_with_data._ensure_loaded()
    # protocol not in file → assumed clean → 1.0
    assert engine_with_data._score_audit_findings_severity({}, "morpho") == 1.0


def test_score_audit_findings_severity_critical(engine_with_data):
    engine_with_data._ensure_loaded()
    # curve: 1 critical + 2 high + 5 medium + 7 low → 1 - 0.30 - 0.30 - 0.25 - 0.07 = 0.08
    s = engine_with_data._score_audit_findings_severity({}, "curve")
    assert 0.0 <= s <= 0.2


@pytest.mark.parametrize("source,expected", [
    ("real_cashflow", 1.0),
    ("rwa", 0.85),
    ("basis", 0.70),
    ("emissions", 0.40),
    ("points", 0.30),
    ("unknown", 0.50),
    ("totally-bogus", 0.50),
])
def test_score_yield_source_type(offline_engine, source, expected):
    assert offline_engine._score_yield_source_type({"yield_source": source}) == expected


@pytest.mark.parametrize("oracle,expected", [
    ("chainlink", 1.0),
    ("pyth", 1.0),
    ("redstone", 0.75),
    ("custom", 0.30),
    ("internal", 0.30),
    ("nonexistent", 0.40),
])
def test_score_oracle_risk(offline_engine, oracle, expected):
    assert offline_engine._score_oracle_risk({"oracle": oracle}) == expected


def test_score_bridge_dependency_native(offline_engine):
    assert offline_engine._score_bridge_dependency({"bridge_dependent": False}) == 1.0


def test_score_bridge_dependency_bridged(offline_engine):
    assert offline_engine._score_bridge_dependency({"bridge_dependent": True}) == 0.30


def test_score_timelock_zero(offline_engine):
    assert offline_engine._score_timelock_duration({"timelock_seconds": 0}) == 0.0


def test_score_timelock_max(offline_engine):
    assert offline_engine._score_timelock_duration({"timelock_seconds": 14 * 24 * 3600}) == 1.0


def test_score_timelock_mid(offline_engine):
    # ~3.5d ≈ 0.5
    s = offline_engine._score_timelock_duration({"timelock_seconds": int(3.5 * 24 * 3600)})
    assert 0.45 < s < 0.55


def test_score_multisig_strong(offline_engine):
    # 4-of-7 → 0.571 ratio < 0.6 → 0.40 + 0.371*1.5 ≈ 0.957
    s = offline_engine._score_multisig_threshold({"multisig_m_of_n": (4, 7)})
    assert s > 0.9


def test_score_multisig_weak(offline_engine):
    s = offline_engine._score_multisig_threshold({"multisig_m_of_n": (1, 5)})
    assert s == 0.20


def test_score_multisig_missing(offline_engine):
    assert offline_engine._score_multisig_threshold({}) == 0.5


def test_score_liquidity_depth_low(offline_engine):
    assert offline_engine._score_liquidity_depth({"liquidity_depth_usd": 5_000_000}) == 0.0


def test_score_liquidity_depth_high(offline_engine):
    assert offline_engine._score_liquidity_depth({"liquidity_depth_usd": 5_000_000_000}) == 1.0


def test_score_liquidity_depth_mid(offline_engine):
    s = offline_engine._score_liquidity_depth({"liquidity_depth_usd": 100_000_000})
    assert 0.3 < s < 0.7


def test_score_cross_protocol_deps_zero(offline_engine):
    assert offline_engine._score_cross_protocol_deps({"cross_protocol_deps": 0}) == 1.0


def test_score_cross_protocol_deps_many(offline_engine):
    assert offline_engine._score_cross_protocol_deps({"cross_protocol_deps": 7}) == 0.0


def test_score_cross_protocol_deps_mid(offline_engine):
    assert offline_engine._score_cross_protocol_deps({"cross_protocol_deps": 2}) == 0.6


def test_score_regulatory_clean(offline_engine):
    assert offline_engine._score_regulatory_surface({"us_exposed": False, "chain": "ethereum"}) == 1.0


def test_score_regulatory_us_exposed(offline_engine):
    assert offline_engine._score_regulatory_surface({"us_exposed": True, "chain": "ethereum"}) == 0.50


def test_score_regulatory_sanctioned(offline_engine):
    assert offline_engine._score_regulatory_surface({"chain": "tron"}) == 0.10


def test_score_chain_maturity_ethereum(offline_engine):
    assert offline_engine._score_chain_maturity({"chain": "ethereum"}) == 1.0


def test_score_chain_maturity_l2(offline_engine):
    assert offline_engine._score_chain_maturity({"chain": "arbitrum"}) == 0.80


def test_score_chain_maturity_new_l1(offline_engine):
    assert offline_engine._score_chain_maturity({"chain": "sui"}) == 0.30


def test_score_chain_maturity_unknown(offline_engine):
    assert offline_engine._score_chain_maturity({"chain": "made-up-chain"}) == 0.40


# ─── 5. compute_score happy path ──────────────────────────────────────────────

def test_compute_score_aave_v3(offline_engine):
    rec = offline_engine.compute_score("aave-v3")
    assert isinstance(rec, se.ProtocolRiskScore)
    assert rec.slug == "aave-v3"
    assert rec.protocol == "Aave V3"
    assert rec.grade in {"A", "B"}
    assert 0.0 <= rec.score_numeric <= 1.0
    assert len(rec.subscores) == 15
    assert rec.explanation


def test_compute_score_unknown_slug_neutral(offline_engine):
    rec = offline_engine.compute_score("totally-unknown-protocol-xyz")
    assert rec.fallback_used is True
    assert rec.slug == "totally-unknown-protocol-xyz"
    # All subscores at 0.5 → numeric = 0.5
    assert rec.score_numeric == 0.5
    assert rec.grade == "D"


def test_compute_score_returns_allocation_cap(offline_engine):
    rec = offline_engine.compute_score("aave-v3")
    assert rec.allocation_cap_pct == se.GRADE_ALLOCATION_CAPS[rec.grade]


def test_compute_score_uses_incidents(engine_with_data):
    rec_with = engine_with_data.compute_score("curve")
    eng2 = se.RiskScoringEngine(
        incidents_file=Path("/nonexistent/incidents.json"),
        audit_file=Path("/nonexistent/audit.json"),
        offline=True,
    )
    rec_without = eng2.compute_score("curve")
    # Score with real incident data must be <= score without (penalty applied)
    assert rec_with.score_numeric <= rec_without.score_numeric + 1e-9


# ─── 6. compute_all ───────────────────────────────────────────────────────────

def test_compute_all_returns_whitelist_length(offline_engine):
    results = offline_engine.compute_all()
    assert len(results) == len(se.SPA_WHITELIST)


def test_compute_all_slugs_match_whitelist(offline_engine):
    results = offline_engine.compute_all()
    assert [r.slug for r in results] == list(se.SPA_WHITELIST)


def test_compute_all_grades_are_valid(offline_engine):
    results = offline_engine.compute_all()
    for r in results:
        assert r.grade in {"A", "B", "C", "D"}


def test_compute_all_custom_slugs(offline_engine):
    results = offline_engine.compute_all(slugs=["aave-v3", "morpho"])
    assert len(results) == 2
    assert {r.slug for r in results} == {"aave-v3", "morpho"}


# ─── 7. Determinism ───────────────────────────────────────────────────────────

def test_compute_all_deterministic(offline_engine):
    r1 = offline_engine.compute_all()
    r2 = offline_engine.compute_all()
    # Strip generated_at and compare the rest
    for a, b in zip(r1, r2):
        ad = a.to_dict()
        bd = b.to_dict()
        ad.pop("generated_at", None)
        bd.pop("generated_at", None)
        assert ad == bd


def test_subscores_deterministic(offline_engine):
    r1 = offline_engine.compute_score("aave-v3")
    r2 = offline_engine.compute_score("aave-v3")
    assert r1.subscores == r2.subscores
    assert r1.score_numeric == r2.score_numeric


# ─── 8. Missing files → graceful degradation ──────────────────────────────────

def test_missing_incidents_sets_fallback(tmp_path):
    eng = se.RiskScoringEngine(
        incidents_file=tmp_path / "does-not-exist.json",
        audit_file=tmp_path / "audit.json",
        offline=True,
    )
    rec = eng.compute_score("aave-v3")
    # hack_history subscore should be neutral 0.5 (degraded)
    assert rec.subscores["hack_history"] == 0.5
    assert rec.fallback_used is True


def test_missing_audit_sets_fallback(tmp_path):
    eng = se.RiskScoringEngine(
        incidents_file=tmp_path / "incidents.json",
        audit_file=tmp_path / "does-not-exist.json",
        offline=True,
    )
    rec = eng.compute_score("aave-v3")
    assert rec.subscores["audit_findings_severity"] == 0.5
    assert rec.fallback_used is True


def test_corrupt_incidents_file(tmp_path):
    p = tmp_path / "incidents.json"
    p.write_text("{ this is not json")
    eng = se.RiskScoringEngine(
        incidents_file=p,
        audit_file=tmp_path / "audit.json",
        offline=True,
    )
    rec = eng.compute_score("aave-v3")
    assert rec.subscores["hack_history"] == 0.5
    assert rec.fallback_used is True


# ─── 9. DefiLlama fetch (mocked) ──────────────────────────────────────────────

def _fake_urlopen(payload):
    """Return a context-manager-style mock for urllib.request.urlopen."""
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = json.dumps(payload).encode()
    cm.__exit__.return_value = False
    return cm


def test_fetch_defillama_protocols_success(tmp_path):
    eng = se.RiskScoringEngine(
        incidents_file=tmp_path / "incidents.json",
        audit_file=tmp_path / "audit.json",
        offline=False,
    )
    payload = [
        {"slug": "aave-v3", "name": "Aave V3", "tvl": 16_000_000_000.0,
         "change_30d": 5.0, "audits": 8, "chain": "Ethereum"},
        {"slug": "newcoin", "name": "NewCoin", "tvl": 100_000_000.0,
         "change_30d": 200.0, "audits": 1, "chain": "Solana"},
    ]
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(payload)):
        out = eng._fetch_defillama_protocols(offline=False)
    assert "aave-v3" in out
    assert "newcoin" in out
    assert out["aave-v3"]["tvl_usd"] == 16_000_000_000.0
    # Bootstrap whitelist entries are still present after merge
    assert "morpho" in out


def test_fetch_defillama_timeout_falls_back(tmp_path):
    eng = se.RiskScoringEngine(
        incidents_file=tmp_path / "incidents.json",
        audit_file=tmp_path / "audit.json",
        offline=False,
        timeout=1,
    )
    with patch("urllib.request.urlopen",
               side_effect=urllib.error.URLError("timeout")), \
         patch("time.sleep"):
        out = eng._fetch_defillama_protocols(offline=False)
    # Falls back to BOOTSTRAP_PROTOCOLS
    for slug in se.SPA_WHITELIST:
        assert slug in out
    assert eng._fallback_used_run is True


def test_offline_flag_skips_network(tmp_path):
    eng = se.RiskScoringEngine(
        incidents_file=tmp_path / "incidents.json",
        audit_file=tmp_path / "audit.json",
        offline=True,
    )
    with patch("urllib.request.urlopen") as mocked:
        eng._fetch_defillama_protocols(offline=True)
    mocked.assert_not_called()


# ─── 10. Export ───────────────────────────────────────────────────────────────

def test_export_dry_run_does_not_write(offline_engine, tmp_path):
    out_path = tmp_path / "risk_scores.json"
    snap = offline_engine.export(output_file=out_path, dry_run=True)
    assert not out_path.exists()
    assert "scores" in snap
    assert len(snap["scores"]) == len(se.SPA_WHITELIST)


def test_export_writes_file(offline_engine, tmp_path):
    out_path = tmp_path / "risk_scores.json"
    offline_engine.export(output_file=out_path, dry_run=False)
    assert out_path.exists()
    loaded = json.loads(out_path.read_text())
    assert "generated_at" in loaded
    assert loaded["engine_version"] == se.ENGINE_VERSION
    assert "weights" in loaded
    assert len(loaded["weights"]) == 15
    assert "scores" in loaded
    assert len(loaded["scores"]) == len(se.SPA_WHITELIST)
    assert "summary_by_grade" in loaded
    assert sum(loaded["summary_by_grade"].values()) == len(loaded["scores"])


def test_export_schema_per_score(offline_engine, tmp_path):
    out_path = tmp_path / "risk_scores.json"
    offline_engine.export(output_file=out_path)
    loaded = json.loads(out_path.read_text())
    for s in loaded["scores"]:
        assert {"protocol", "slug", "grade", "score_numeric", "subscores",
                "explanation", "allocation_cap_pct", "fallback_used",
                "generated_at"} <= set(s.keys())
        assert len(s["subscores"]) == 15


def test_export_summary_grade_counts(offline_engine, tmp_path):
    out_path = tmp_path / "risk_scores.json"
    snap = offline_engine.export(output_file=out_path)
    by_g = snap["summary_by_grade"]
    assert set(by_g.keys()) == {"A", "B", "C", "D"}
    assert sum(by_g.values()) == len(snap["scores"])


def test_export_round_trip(offline_engine, tmp_path):
    out_path = tmp_path / "risk_scores.json"
    snap = offline_engine.export(output_file=out_path)
    loaded = json.loads(out_path.read_text())
    # Strip the dynamic generated_at for comparison
    snap.pop("generated_at", None)
    loaded.pop("generated_at", None)
    for s in snap["scores"]:
        s.pop("generated_at", None)
    for s in loaded["scores"]:
        s.pop("generated_at", None)
    assert snap == loaded


# ─── 11. ProtocolRiskScore dataclass ──────────────────────────────────────────

def test_dataclass_to_dict_keys():
    rec = se.ProtocolRiskScore(
        protocol="Aave V3",
        slug="aave-v3",
        grade="A",
        score_numeric=0.9,
        subscores={"tvl_magnitude": 1.0},
        explanation="test",
        generated_at="2026-05-27T00:00:00Z",
    )
    d = rec.to_dict()
    assert d["protocol"] == "Aave V3"
    assert d["grade"] == "A"
    assert d["fallback_used"] is False
    assert d["allocation_cap_pct"] is None


# ─── 12. CLI smoke ────────────────────────────────────────────────────────────

def test_cli_offline_dry_run(tmp_path, monkeypatch):
    out_path = tmp_path / "risk_scores.json"
    rc = se._cli(["--offline", "--dry-run", "--output", str(out_path)])
    assert rc == 0
    assert not out_path.exists()


def test_cli_offline_writes(tmp_path):
    out_path = tmp_path / "risk_scores.json"
    rc = se._cli(["--offline", "--output", str(out_path)])
    assert rc == 0
    assert out_path.exists()
    loaded = json.loads(out_path.read_text())
    assert len(loaded["scores"]) == len(se.SPA_WHITELIST)


def test_cli_single_protocol(tmp_path):
    out_path = tmp_path / "risk_scores.json"
    rc = se._cli(["--offline", "--protocol", "aave-v3", "--output", str(out_path)])
    assert rc == 0
    loaded = json.loads(out_path.read_text())
    assert len(loaded["scores"]) == 1
    assert loaded["scores"][0]["slug"] == "aave-v3"
