"""
Tests for spa_core/agents/yield_classifier_agent.py (FEAT-RISK-003).

Deterministic, fully offline test suite. Every network call is patched —
no real HTTP traffic ever leaves the test process. No mutation of the
production ``data/yield_sources.json`` or ``data/risk_scores.json`` files.

Coverage:
  1. _normalize_protocol_name — alias map for whitelist pool slugs
  2. _coerce_primary_source — canonical taxonomy + synonyms
  3. _coerce_confidence — HIGH/MEDIUM/LOW coercion
  4. _clamp_emissions_pct — [0,100] clamp + error tolerance
  5. BOOTSTRAP_CLASSIFICATIONS covers every SPA whitelist slug
  6. classify_all(offline=True) returns 1 YieldClassification per slug
  7. classify_all is deterministic across calls (byte-equal excl. timestamp)
  8. Field validations: primary_source ∈ YIELD_SOURCES, confidence ∈ levels
  9. emissions_share_pct ∈ [0, 100]
 10. Summary.by_primary_source sums to total_protocols
 11. high_emissions_count matches pct>50 protocols
 12. unknown_count matches primary_source=="unknown" count
 13. export(dry_run=True) does not write a file
 14. export() writes valid JSON to disk and round-trips
 15. classify_one for unknown slug -> "unknown" classification, no raise
 16. classify_one for empty/None slug -> "unknown", no raise
 17. enrich_risk_scores no-op when file is missing
 18. enrich_risk_scores no-op when file is unreadable / garbage
 19. enrich_risk_scores merges yield_source for "scores" list schema
 20. enrich_risk_scores merges yield_source for "protocols" dict schema
 21. enrich_risk_scores is byte-stable when called twice in dry-run
 22. CLI smoke (_cli with --dry-run --offline returns 0)
 23. Offline mode does not call urllib.request.urlopen
 24. classify_all never raises on network failure (sets fallback_used)
 25. Specific bootstrap entries (Aave, Ethena sUSDe, Pendle PT, Curve)
 26. Snapshot top-level keys
 27. AGENT_VERSION constant is non-empty string
 28. Secondary sources are validated against the canonical taxonomy
 29. Each bootstrap rationale is non-empty
 30. Default output path lands in data/yield_sources.json
 31. Sorted protocols keys in snapshot
 32. Snapshot summary block well-formed

These tests are designed to run with:

    pytest -q spa_core/tests/test_yield_classifier_agent.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure spa_core is importable when pytest is run from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.agents import yield_classifier_agent as yca
from spa_core.agents.yield_classifier_agent import (
    AGENT_VERSION,
    CONFIDENCE_LEVELS,
    SPA_WHITELIST,
    YIELD_SOURCES,
    YieldClassification,
    YieldClassifierAgent,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def agent(tmp_path):
    """A fresh YieldClassifierAgent writing into tmp_path (no prod writes)."""
    out = tmp_path / "yield_sources.json"
    risk = tmp_path / "risk_scores.json"
    return YieldClassifierAgent(output_file=out, risk_scores_file=risk)


# ─── 1. _normalize_protocol_name ──────────────────────────────────────────────

@pytest.mark.parametrize("inp,expected", [
    ("Aave Protocol V3",   "aave-v3"),
    ("Aave V3",            "aave-v3"),
    ("Aave",               "aave-v3"),
    ("Compound III",       "compound-v3"),
    ("Compound v3",        "compound-v3"),
    ("Morpho Blue",        "morpho"),
    ("Yearn V3",           "yearn-v3"),
    ("Sky / sUSDS",        "sky"),
    ("MakerDAO",           "sky"),
    ("Maple Finance",      "maple"),
    ("Euler V2",           "euler-v2"),
    ("Pendle",             "pendle-pt"),
    ("Pendle PT",          "pendle-pt"),
    ("Curve USDC/USDT",    "curve-usdc-usdt"),
    ("Uniswap V3",         "uniswap-v3-stable"),
    ("Ethena sUSDe",       "ethena-susde"),
    ("Spark USDC",         "spark-usdc"),
    ("Fluid USDC",         "fluid-usdc"),
    ("Instadapp",          "fluid-usdc"),
    ("",                   ""),
    (None,                 ""),
])
def test_normalize_protocol_name(agent, inp, expected):
    assert agent._normalize_protocol_name(inp) == expected


# ─── 2. _coerce_primary_source ────────────────────────────────────────────────

@pytest.mark.parametrize("inp,expected", [
    ("real_cashflow",   "real_cashflow"),
    ("REAL_CASHFLOW",   "real_cashflow"),
    ("real-cashflow",   "real_cashflow"),
    ("lending",         "real_cashflow"),
    ("interest",        "real_cashflow"),
    ("fees",            "real_cashflow"),
    ("swap_fees",       "real_cashflow"),
    ("token_emissions", "token_emissions"),
    ("emissions",       "token_emissions"),
    ("rewards",         "token_emissions"),
    ("incentives",      "token_emissions"),
    ("points_farming",  "points_farming"),
    ("points",          "points_farming"),
    ("basis_trade",     "basis_trade"),
    ("basis",           "basis_trade"),
    ("funding",         "basis_trade"),
    ("rwa",             "rwa"),
    ("real_world",      "rwa"),
    ("treasury",        "rwa"),
    ("unknown",         "unknown"),
    ("",                "unknown"),
    (None,              "unknown"),
    ("nonsense_xyz",    "unknown"),
])
def test_coerce_primary_source(inp, expected):
    assert YieldClassifierAgent._coerce_primary_source(inp) == expected


# ─── 3. _coerce_confidence ────────────────────────────────────────────────────

@pytest.mark.parametrize("inp,expected", [
    ("HIGH",   "HIGH"),
    ("High",   "HIGH"),
    ("high",   "HIGH"),
    ("H",      "HIGH"),
    ("HI",     "HIGH"),
    ("MEDIUM", "MEDIUM"),
    ("Medium", "MEDIUM"),
    ("M",      "MEDIUM"),
    ("MED",    "MEDIUM"),
    ("LOW",    "LOW"),
    ("L",      "LOW"),
    ("LO",     "LOW"),
    ("",       "LOW"),
    (None,     "LOW"),
    ("???",    "LOW"),
])
def test_coerce_confidence(inp, expected):
    assert YieldClassifierAgent._coerce_confidence(inp) == expected


# ─── 4. _clamp_emissions_pct ──────────────────────────────────────────────────

@pytest.mark.parametrize("inp,expected", [
    (0,      0),
    (50,     50),
    (100,    100),
    (-5,     0),
    (150,    100),
    ("42",   42),
    ("12.6", 13),    # rounds nearest
    (None,   0),
    ("abc",  0),
])
def test_clamp_emissions_pct(inp, expected):
    assert YieldClassifierAgent._clamp_emissions_pct(inp) == expected


# ─── 5. BOOTSTRAP covers full whitelist ───────────────────────────────────────

def test_bootstrap_covers_full_whitelist():
    """Every SPA whitelist slug must have a bootstrap classification."""
    slugs = {rec["protocol_slug"] for rec in yca.BOOTSTRAP_CLASSIFICATIONS}
    missing = set(SPA_WHITELIST) - slugs
    assert not missing, f"missing whitelist slugs in bootstrap: {missing}"


def test_bootstrap_has_no_extras():
    """Bootstrap must not have slugs outside the whitelist (yet)."""
    slugs = {rec["protocol_slug"] for rec in yca.BOOTSTRAP_CLASSIFICATIONS}
    extras = slugs - set(SPA_WHITELIST)
    assert not extras, f"unexpected slugs in bootstrap: {extras}"


def test_bootstrap_fields_are_valid():
    """Every bootstrap entry has valid taxonomy / confidence / pct values."""
    for rec in yca.BOOTSTRAP_CLASSIFICATIONS:
        assert rec["primary_source"] in YIELD_SOURCES, (
            f"{rec['protocol_slug']}: bad primary_source {rec['primary_source']}"
        )
        for s in rec.get("secondary_sources", []):
            assert s in YIELD_SOURCES, (
                f"{rec['protocol_slug']}: bad secondary_source {s}"
            )
        assert rec["confidence"] in CONFIDENCE_LEVELS, (
            f"{rec['protocol_slug']}: bad confidence {rec['confidence']}"
        )
        pct = rec["emissions_share_pct"]
        assert 0 <= pct <= 100, (
            f"{rec['protocol_slug']}: emissions_share_pct out of range {pct}"
        )
        assert isinstance(rec.get("rationale", ""), str)
        assert rec.get("rationale", ""), f"{rec['protocol_slug']}: empty rationale"


# ─── 6. classify_all returns one entry per slug ───────────────────────────────

def test_classify_all_returns_one_per_whitelist_slug(agent):
    classifications = agent.classify_all(offline=True)
    assert set(classifications.keys()) == set(SPA_WHITELIST)
    for slug, c in classifications.items():
        assert isinstance(c, YieldClassification)
        assert c.protocol_slug == slug


# ─── 7. Offline mode does not hit the network ─────────────────────────────────

def test_classify_all_offline_does_not_call_urlopen(agent):
    with patch("urllib.request.urlopen") as mock_urlopen:
        agent.classify_all(offline=True)
    mock_urlopen.assert_not_called()


def test_export_offline_does_not_call_urlopen(agent):
    with patch("urllib.request.urlopen") as mock_urlopen:
        agent.export(offline=True, dry_run=True)
    mock_urlopen.assert_not_called()


# ─── 8. Field-level validity invariants ───────────────────────────────────────

def test_every_classification_has_canonical_primary_source(agent):
    classifications = agent.classify_all(offline=True)
    for slug, c in classifications.items():
        assert c.primary_source in YIELD_SOURCES, (
            f"{slug}: bad primary_source {c.primary_source}"
        )


def test_every_classification_has_canonical_confidence(agent):
    classifications = agent.classify_all(offline=True)
    for slug, c in classifications.items():
        assert c.confidence in CONFIDENCE_LEVELS, (
            f"{slug}: bad confidence {c.confidence}"
        )


def test_every_classification_has_valid_emissions_pct(agent):
    classifications = agent.classify_all(offline=True)
    for slug, c in classifications.items():
        assert 0 <= c.emissions_share_pct <= 100, (
            f"{slug}: emissions_share_pct out of range {c.emissions_share_pct}"
        )


def test_every_classification_has_non_empty_rationale(agent):
    classifications = agent.classify_all(offline=True)
    for slug, c in classifications.items():
        assert isinstance(c.rationale, str)
        assert len(c.rationale) > 0, f"{slug}: empty rationale"


def test_every_classification_has_data_sources(agent):
    classifications = agent.classify_all(offline=True)
    for slug, c in classifications.items():
        assert "bootstrap" in c.data_sources, (
            f"{slug}: data_sources missing bootstrap {c.data_sources}"
        )


# ─── 9. Determinism ───────────────────────────────────────────────────────────

def test_classify_all_is_deterministic(agent):
    a = agent.classify_all(offline=True)
    b = agent.classify_all(offline=True)

    def normalise(classifications):
        return {
            slug: (
                c.primary_source,
                tuple(sorted(c.secondary_sources)),
                c.confidence,
                c.emissions_share_pct,
                c.rationale,
                tuple(sorted(c.data_sources)),
                c.classified_at,
            )
            for slug, c in classifications.items()
        }

    assert normalise(a) == normalise(b)


def test_snapshot_protocols_byte_equal_across_runs(agent):
    """Two snapshots should be byte-identical excluding generated_at."""
    a = agent.export(offline=True, dry_run=True)
    b = agent.export(offline=True, dry_run=True)
    a_copy = dict(a)
    b_copy = dict(b)
    a_copy.pop("generated_at")
    b_copy.pop("generated_at")
    assert json.dumps(a_copy, sort_keys=True) == json.dumps(b_copy, sort_keys=True)


def test_snapshot_protocols_keys_are_sorted(agent):
    snap = agent.export(offline=True, dry_run=True)
    keys = list(snap["protocols"].keys())
    assert keys == sorted(keys)


# ─── 10. Snapshot summary cross-check ─────────────────────────────────────────

def test_summary_by_primary_sums_to_total_protocols(agent):
    snap = agent.export(offline=True, dry_run=True)
    by_p = snap["summary"]["by_primary_source"]
    total = snap["summary"]["total_protocols"]
    assert sum(by_p.values()) == total


def test_summary_high_emissions_matches_protocols(agent):
    snap = agent.export(offline=True, dry_run=True)
    expected = sum(1 for p in snap["protocols"].values()
                   if p["emissions_share_pct"] > 50)
    assert snap["summary"]["high_emissions_count"] == expected


def test_summary_unknown_count_matches_protocols(agent):
    snap = agent.export(offline=True, dry_run=True)
    expected = sum(1 for p in snap["protocols"].values()
                   if p["primary_source"] == "unknown")
    assert snap["summary"]["unknown_count"] == expected


def test_summary_by_primary_keys_are_all_canonical(agent):
    snap = agent.export(offline=True, dry_run=True)
    keys = set(snap["summary"]["by_primary_source"].keys())
    assert keys == set(YIELD_SOURCES)


# ─── 11. Export ───────────────────────────────────────────────────────────────

def test_export_dry_run_does_not_write_file(agent):
    assert not agent.output_file.exists()
    snap = agent.export(offline=True, dry_run=True)
    assert not agent.output_file.exists()
    assert snap["summary"]["total_protocols"] == len(SPA_WHITELIST)


def test_export_writes_file_and_round_trips(agent):
    out_path = agent.output_file
    assert not out_path.exists()
    snap = agent.export(offline=True, dry_run=False)
    assert out_path.exists()
    on_disk = json.loads(out_path.read_text(encoding="utf-8"))
    assert on_disk["agent_version"] == AGENT_VERSION
    assert on_disk["summary"]["total_protocols"] == len(SPA_WHITELIST)
    assert set(on_disk["protocols"].keys()) == set(SPA_WHITELIST)
    assert on_disk["protocols"] == snap["protocols"]


def test_snapshot_top_level_keys(agent):
    snap = agent.export(offline=True, dry_run=True)
    for k in ("generated_at", "agent_version", "sources", "fallback_used",
              "protocols", "summary"):
        assert k in snap, f"missing key {k}"


def test_snapshot_sources_list_includes_bootstrap(agent):
    snap = agent.export(offline=True, dry_run=True)
    assert "bootstrap" in snap["sources"]


def test_snapshot_fallback_used_true_when_offline(agent):
    snap = agent.export(offline=True, dry_run=True)
    assert snap["fallback_used"] is True


# ─── 12. classify_one error tolerance ─────────────────────────────────────────

def test_classify_one_unknown_slug_returns_unknown(agent):
    c = agent.classify_one("does-not-exist")
    assert c.primary_source == "unknown"
    assert c.confidence == "LOW"
    assert c.protocol_slug == "does-not-exist"


def test_classify_one_empty_slug_returns_unknown(agent):
    c = agent.classify_one("")
    assert c.primary_source == "unknown"
    assert c.protocol_slug == ""


def test_classify_one_known_slug_returns_real_data(agent):
    c = agent.classify_one("aave-v3")
    assert c.primary_source == "real_cashflow"
    assert c.confidence == "HIGH"


# ─── 13. Bootstrap content sanity ─────────────────────────────────────────────

def test_aave_v3_is_real_cashflow(agent):
    classifications = agent.classify_all(offline=True)
    assert classifications["aave-v3"].primary_source == "real_cashflow"
    assert classifications["aave-v3"].emissions_share_pct == 0


def test_ethena_susde_is_basis_trade(agent):
    classifications = agent.classify_all(offline=True)
    assert classifications["ethena-susde"].primary_source == "basis_trade"


def test_pendle_pt_is_basis_trade(agent):
    classifications = agent.classify_all(offline=True)
    assert classifications["pendle-pt"].primary_source == "basis_trade"


def test_curve_has_token_emissions_secondary(agent):
    classifications = agent.classify_all(offline=True)
    curve = classifications["curve-usdc-usdt"]
    assert curve.primary_source == "real_cashflow"
    assert "token_emissions" in curve.secondary_sources


def test_sky_has_rwa_secondary(agent):
    classifications = agent.classify_all(offline=True)
    sky = classifications["sky"]
    assert sky.primary_source == "real_cashflow"
    assert "rwa" in sky.secondary_sources


def test_uniswap_stable_is_real_cashflow(agent):
    classifications = agent.classify_all(offline=True)
    assert classifications["uniswap-v3-stable"].primary_source == "real_cashflow"


# ─── 14. Network failure tolerance ────────────────────────────────────────────

def test_classify_all_does_not_raise_on_network_failure(agent):
    """If the remote stub raises, classify_all still produces output."""
    def boom(*a, **kw):
        raise urllib.error.URLError("simulated network down")

    with patch.object(agent, "_fetch_remote_classifications",
                       side_effect=boom):
        classifications = agent.classify_all(offline=False)

    # Falls back to bootstrap — every whitelist slug present.
    assert set(classifications.keys()) == set(SPA_WHITELIST)
    assert agent._fallback_used is True


def test_export_does_not_raise_when_classify_blows_up(agent):
    """Even a catastrophic failure in classify_all is swallowed."""
    def boom(*a, **kw):
        raise RuntimeError("simulated catastrophe")

    with patch.object(agent, "classify_all", side_effect=boom):
        snap = agent.export(offline=True, dry_run=True)

    # We still get a full snapshot for every slug, all "unknown".
    assert set(snap["protocols"].keys()) == set(SPA_WHITELIST)
    assert snap["fallback_used"] is True


# ─── 15. enrich_risk_scores — no-op cases ─────────────────────────────────────

def test_enrich_no_op_when_file_missing(agent):
    """Missing risk_scores.json -> no-op, returns False, no raise."""
    assert not agent.risk_scores_file.exists()
    ok = agent.enrich_risk_scores()
    assert ok is False


def test_enrich_no_op_when_file_garbage(agent):
    """Unreadable / non-JSON risk_scores.json -> no-op, returns False."""
    agent.risk_scores_file.parent.mkdir(parents=True, exist_ok=True)
    agent.risk_scores_file.write_text("<html>not json</html>",
                                       encoding="utf-8")
    ok = agent.enrich_risk_scores()
    assert ok is False


def test_enrich_no_op_when_root_is_list(agent):
    """If risk_scores.json is a list (not dict), skip gracefully."""
    agent.risk_scores_file.parent.mkdir(parents=True, exist_ok=True)
    agent.risk_scores_file.write_text(json.dumps([1, 2, 3]),
                                       encoding="utf-8")
    ok = agent.enrich_risk_scores()
    assert ok is False


# ─── 16. enrich_risk_scores — protocols-dict schema ──────────────────────────

def test_enrich_merges_protocols_dict_schema(agent):
    """Schema A: { protocols: { slug: {...} } } gets yield_source merged in."""
    payload = {
        "protocols": {
            "aave-v3":       {"grade": "A"},
            "ethena-susde":  {"grade": "C"},
            "irrelevant":    {"grade": "Z"},
        }
    }
    agent.risk_scores_file.parent.mkdir(parents=True, exist_ok=True)
    agent.risk_scores_file.write_text(json.dumps(payload), encoding="utf-8")

    ok = agent.enrich_risk_scores()
    assert ok is True

    on_disk = json.loads(agent.risk_scores_file.read_text(encoding="utf-8"))
    assert on_disk["protocols"]["aave-v3"]["yield_source"] == "real_cashflow"
    assert on_disk["protocols"]["ethena-susde"]["yield_source"] == "basis_trade"
    # Non-whitelist slugs untouched.
    assert "yield_source" not in on_disk["protocols"]["irrelevant"]


# ─── 17. enrich_risk_scores — scores-list schema ──────────────────────────────

def test_enrich_merges_scores_list_schema(agent):
    """Schema B: { scores: [ {slug: ..., ...}, ... ] } gets yield_source."""
    payload = {
        "scores": [
            {"slug": "aave-v3",       "grade": "A"},
            {"slug": "ethena-susde",  "grade": "C"},
            {"slug": "pendle-pt",     "grade": "B"},
            {"slug": "not-in-set",    "grade": "Z"},
            "not-a-dict",
        ]
    }
    agent.risk_scores_file.parent.mkdir(parents=True, exist_ok=True)
    agent.risk_scores_file.write_text(json.dumps(payload), encoding="utf-8")

    ok = agent.enrich_risk_scores()
    assert ok is True

    on_disk = json.loads(agent.risk_scores_file.read_text(encoding="utf-8"))
    found = {e["slug"]: e for e in on_disk["scores"] if isinstance(e, dict)}
    assert found["aave-v3"]["yield_source"] == "real_cashflow"
    assert found["ethena-susde"]["yield_source"] == "basis_trade"
    assert found["pendle-pt"]["yield_source"] == "basis_trade"
    assert "yield_source" not in found["not-in-set"]


def test_enrich_dry_run_does_not_modify_file(agent):
    """dry_run=True must leave the input file untouched on disk."""
    payload = {"scores": [{"slug": "aave-v3", "grade": "A"}]}
    text = json.dumps(payload)
    agent.risk_scores_file.parent.mkdir(parents=True, exist_ok=True)
    agent.risk_scores_file.write_text(text, encoding="utf-8")

    ok = agent.enrich_risk_scores(dry_run=True)
    assert ok is True
    assert agent.risk_scores_file.read_text(encoding="utf-8") == text


def test_enrich_is_idempotent(agent):
    """Running enrich twice must produce the same yield_source field set."""
    payload = {"scores": [{"slug": "aave-v3", "grade": "A"},
                          {"slug": "sky", "grade": "B"}]}
    agent.risk_scores_file.parent.mkdir(parents=True, exist_ok=True)
    agent.risk_scores_file.write_text(json.dumps(payload), encoding="utf-8")

    agent.enrich_risk_scores()
    first = agent.risk_scores_file.read_text(encoding="utf-8")
    agent.enrich_risk_scores()
    second = agent.risk_scores_file.read_text(encoding="utf-8")
    assert first == second


# ─── 18. Unknown record is filtered, never added ──────────────────────────────

def test_unknown_protocol_records_are_ignored(agent):
    """A record with an unrecognised slug must not pollute the snapshot."""
    real = agent._bootstrap_records()
    real.append({
        "protocol_slug":       "junk-protocol",
        "primary_source":      "real_cashflow",
        "secondary_sources":   [],
        "confidence":          "HIGH",
        "emissions_share_pct": 0,
        "rationale":           "junk",
        "data_sources":        ["bootstrap"],
        "classified_at":       "2026-05-28",
    })
    with patch.object(agent, "_bootstrap_records", return_value=real):
        classifications = agent.classify_all(offline=True)
    assert "junk-protocol" not in classifications
    assert set(classifications.keys()) == set(SPA_WHITELIST)


# ─── 19. CLI smoke ────────────────────────────────────────────────────────────

def test_cli_smoke_dry_run_offline(tmp_path):
    """_cli with --offline --dry-run --no-enrich must return 0 cleanly."""
    out = tmp_path / "yield_sources.json"
    risk = tmp_path / "risk_scores.json"
    rc = yca._cli(["--offline", "--dry-run", "--no-enrich",
                    "--output", str(out), "--risk-scores", str(risk)])
    assert rc == 0
    # --dry-run means no file was written
    assert not out.exists()


def test_cli_smoke_writes_file(tmp_path):
    """_cli without --dry-run writes the snapshot."""
    out = tmp_path / "yield_sources.json"
    risk = tmp_path / "risk_scores.json"
    rc = yca._cli(["--offline", "--no-enrich",
                    "--output", str(out), "--risk-scores", str(risk)])
    assert rc == 0
    assert out.exists()
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["summary"]["total_protocols"] == len(SPA_WHITELIST)


# ─── 20. Constants sanity ─────────────────────────────────────────────────────

def test_agent_version_is_non_empty_string():
    assert isinstance(AGENT_VERSION, str)
    assert AGENT_VERSION


def test_default_output_path_is_data_yield_sources_json():
    a = YieldClassifierAgent()
    assert a.output_file.name == "yield_sources.json"
    assert a.output_file.parent.name == "data"


def test_whitelist_contains_expected_minimum_slugs():
    """Spec requires these slugs at minimum."""
    required = {
        "aave-v3", "compound-v3", "morpho", "yearn-v3", "sky", "maple",
        "euler-v2", "pendle-pt", "curve-usdc-usdt", "uniswap-v3-stable",
        "ethena-susde", "spark-usdc", "fluid-usdc",
    }
    assert required <= set(SPA_WHITELIST)


def test_yield_sources_taxonomy_is_locked():
    """The canonical taxonomy is the public contract — assert its members."""
    assert set(YIELD_SOURCES) == {
        "real_cashflow", "token_emissions", "points_farming",
        "basis_trade", "rwa", "unknown",
    }
