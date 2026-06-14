"""
Tests for spa_core/alerts/red_flag_monitor.py (FEAT-MON-001).

Deterministic, fully offline. No network traffic ever leaves the test
process — every HTTP entry point is patched. The production ``data/``
directory is not mutated: every fixture uses ``tmp_path``.

Coverage matrix
---------------
A. Dataclass / constants sanity                       (4 tests)
B. Severity classification for every category         (8 tests)
C. JSON shape / summary                               (5 tests)
D. Risk-grade context loading                         (3 tests)
E. Fallback paths on missing / unreadable files       (3 tests)
F. Network fetch hooks (TVL / APY / governance / unlock)
                                                       (8 tests)
G. CLI + offline determinism                          (3 tests)
H. Module-level helpers + edge cases                  (6+ tests)

Total: 40+ tests.

Run with:

    pytest -q spa_core/tests/test_red_flag_monitor.py
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

from spa_core.alerts import red_flag_monitor as rfm
from spa_core.alerts.red_flag_monitor import (
    APY_SPIKE_CRITICAL_RATIO,
    APY_SPIKE_MULTIPLIER,
    BOOTSTRAP_APY_SPIKES,
    BOOTSTRAP_GOVERNANCE_PROPOSALS,
    BOOTSTRAP_TOKEN_UNLOCKS,
    BOOTSTRAP_TVL_DROPS,
    CATEGORIES,
    GOVERNANCE_CRITICAL_TAGS,
    GOVERNANCE_RISK_TAGS,
    MONITOR_VERSION,
    RedFlag,
    RedFlagMonitor,
    SEVERITIES,
    SPA_WHITELIST,
    TVL_DROP_24H_THRESHOLD_PCT,
    TVL_DROP_7D_THRESHOLD_PCT,
    TVL_DROP_CRITICAL_PCT,
    UNLOCK_CRITICAL_PCT_SUPPLY,
    UNLOCK_HORIZON_DAYS,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def monitor(tmp_path):
    """A fresh RedFlagMonitor whose files all live in tmp_path."""
    out  = tmp_path / "red_flags.json"
    rs   = tmp_path / "risk_scores.json"
    apy  = tmp_path / "historical_apy.json"
    return RedFlagMonitor(
        output_file=out,
        risk_scores_file=rs,
        historical_apy_file=apy,
    )


@pytest.fixture
def grades_a_to_d(tmp_path):
    """Write a synthetic risk_scores.json covering 4 grades."""
    p = tmp_path / "risk_scores.json"
    doc = {
        "generated_at": "2026-05-28T00:00:00Z",
        "scores": [
            {"slug": "aave-v3",        "grade": "A"},
            {"slug": "compound-v3",    "grade": "B"},
            {"slug": "morpho",         "grade": "C"},
            {"slug": "euler-v2",       "grade": "D"},
            {"slug": "pendle-pt",      "grade": "A"},
            {"slug": "ethena-susde",   "grade": "B"},
            {"slug": "maple",          "grade": "C"},
        ],
    }
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


# ─── A. Dataclass / constants ─────────────────────────────────────────────────


def test_monitor_version_is_non_empty_string():
    assert isinstance(MONITOR_VERSION, str) and MONITOR_VERSION


def test_categories_and_severities_canonical():
    assert set(CATEGORIES) == {
        "tvl_drop", "apy_spike", "governance_proposal", "token_unlock"}
    assert set(SEVERITIES) == {"WARN", "CRITICAL"}


def test_red_flag_to_dict_round_trip():
    f = RedFlag(
        protocol="aave-v3",
        category="tvl_drop",
        severity="WARN",
        message="hello",
        source="defillama",
        detected_at="2026-05-28T00:00:00Z",
        evidence={"b": 2, "a": 1},
    )
    d = f.to_dict()
    assert d["protocol"] == "aave-v3"
    assert d["category"] == "tvl_drop"
    assert d["evidence"] == {"a": 1, "b": 2}
    # Keys of evidence are sorted for determinism.
    assert list(d["evidence"].keys()) == ["a", "b"]


def test_bootstrap_fixtures_cover_whitelist_subsets():
    # All bootstrap protocols must be SPA whitelist members.
    for rec in BOOTSTRAP_TVL_DROPS:
        assert rec["protocol"] in SPA_WHITELIST
    for rec in BOOTSTRAP_APY_SPIKES:
        assert rec["protocol"] in SPA_WHITELIST
    for rec in BOOTSTRAP_GOVERNANCE_PROPOSALS:
        assert rec["protocol"] in SPA_WHITELIST
    for rec in BOOTSTRAP_TOKEN_UNLOCKS:
        assert rec["protocol"] in SPA_WHITELIST


# ─── B. Severity classification ───────────────────────────────────────────────


def test_tvl_drop_warn_for_grade_a(monitor):
    grades = {"aave-v3": "A"}
    flags = monitor._classify_tvl_drops([{
        "protocol":    "aave-v3",
        "delta_24h":   -16.0,
        "delta_7d":    -10.0,
        "tvl_now":     1.0e9,
        "tvl_24h_ago": 1.2e9,
        "tvl_7d_ago":  1.1e9,
    }], grades)
    assert len(flags) == 1
    assert flags[0].severity == "WARN"
    assert flags[0].category == "tvl_drop"


def test_tvl_drop_critical_for_poor_grade(monitor):
    grades = {"euler-v2": "D"}
    flags = monitor._classify_tvl_drops([{
        "protocol":    "euler-v2",
        "delta_24h":   -16.0,
        "delta_7d":    -10.0,
        "tvl_now":     1.0e9,
        "tvl_24h_ago": 1.2e9,
        "tvl_7d_ago":  1.1e9,
    }], grades)
    assert flags[0].severity == "CRITICAL"


def test_tvl_drop_critical_when_magnitude_exceeds_threshold(monitor):
    # > 50% drop is unconditionally CRITICAL even on grade A.
    grades = {"aave-v3": "A"}
    flags = monitor._classify_tvl_drops([{
        "protocol":    "aave-v3",
        "delta_24h":   -55.0,
        "delta_7d":    -10.0,
        "tvl_now":     4.5e8,
        "tvl_24h_ago": 1.0e9,
        "tvl_7d_ago":  1.0e9,
    }], grades)
    assert flags[0].severity == "CRITICAL"


def test_tvl_drop_below_thresholds_emits_nothing(monitor):
    flags = monitor._classify_tvl_drops([{
        "protocol":    "aave-v3",
        "delta_24h":   -5.0,
        "delta_7d":    -10.0,
        "tvl_now":     9.5e8,
        "tvl_24h_ago": 1.0e9,
        "tvl_7d_ago":  1.05e9,
    }], {})
    assert flags == []


def test_apy_spike_warn_then_critical(monitor):
    grades = {"ethena-susde": "B", "pendle-pt": "A"}
    flags = monitor._classify_apy_spikes([
        {"protocol": "ethena-susde", "current": 12.0, "baseline": 7.0},
        {"protocol": "pendle-pt",    "current": 30.0, "baseline": 6.0},
    ], grades)
    assert len(flags) == 2
    sev = {f.protocol: f.severity for f in flags}
    # 12/7=1.71x → WARN, 30/6=5x → CRITICAL (above APY_SPIKE_CRITICAL_RATIO)
    assert sev["ethena-susde"] == "WARN"
    assert sev["pendle-pt"]    == "CRITICAL"


def test_apy_spike_ignored_when_baseline_below_min(monitor):
    flags = monitor._classify_apy_spikes([
        {"protocol": "aave-v3", "current": 5.0, "baseline": 0.001},
    ], {})
    assert flags == []


def test_governance_proposal_critical_for_emergency_tag(monitor):
    flags = monitor._classify_governance([
        {
            "protocol":    "aave-v3",
            "proposal_id": "0xabc",
            "title":       "Emergency pause",
            "tag":         "emergency",
            "deadline":    "",
            "space":       "aave.eth",
        }
    ], {"aave-v3": "A"})
    assert len(flags) == 1
    assert flags[0].severity == "CRITICAL"
    assert flags[0].category == "governance_proposal"


def test_governance_warn_for_upgrade_on_grade_a(monitor):
    flags = monitor._classify_governance([
        {
            "protocol":    "aave-v3",
            "proposal_id": "0xabc",
            "title":       "Routine upgrade of comet",
            "tag":         "upgrade",
            "deadline":    "",
            "space":       "aave.eth",
        }
    ], {"aave-v3": "A"})
    assert flags[0].severity == "WARN"


def test_token_unlock_critical_when_supply_above_threshold(monitor):
    grades = {"ethena-susde": "B"}
    flags = monitor._classify_unlocks([
        {
            "protocol":   "ethena-susde",
            "unlock_at":  "2026-06-03T00:00:00Z",
            "pct_supply": 8.0,
            "tokens":     420_000_000,
            "symbol":     "ENA",
        }
    ], grades)
    assert flags[0].severity == "CRITICAL"


def test_token_unlock_warn_for_low_supply_on_grade_a(monitor):
    grades = {"pendle-pt": "A"}
    flags = monitor._classify_unlocks([
        {
            "protocol":   "pendle-pt",
            "unlock_at":  "2026-06-01T00:00:00Z",
            "pct_supply": 1.0,
            "tokens":     5_400_000,
            "symbol":     "PENDLE",
        }
    ], grades)
    assert flags[0].severity == "WARN"


# ─── C. JSON shape / summary ──────────────────────────────────────────────────


def test_scan_all_offline_returns_flags(monitor):
    flags = monitor.scan_all(offline=True)
    assert isinstance(flags, list)
    assert len(flags) >= 4  # at least one per category
    cats = {f.category for f in flags}
    assert cats == set(CATEGORIES)


def test_export_offline_writes_valid_json(monitor):
    snap = monitor.export(offline=True)
    assert monitor.output_file.exists()
    doc = json.loads(monitor.output_file.read_text())
    assert doc["monitor_version"] == MONITOR_VERSION
    assert doc["fallback_used"] is True
    assert isinstance(doc["red_flags"], list)
    assert "summary" in doc
    s = doc["summary"]
    assert s["total_flags"] == len(doc["red_flags"])
    # By-category sum equals total.
    assert sum(s["by_category"].values()) == s["total_flags"]
    assert sum(s["by_severity"].values()) == s["total_flags"]


def test_dry_run_does_not_write(monitor):
    assert not monitor.output_file.exists()
    snap = monitor.export(offline=True, dry_run=True)
    assert isinstance(snap, dict)
    assert not monitor.output_file.exists()


def test_summary_keys_present(monitor):
    snap = monitor.export(offline=True, dry_run=True)
    s = snap["summary"]
    for k in ("total_flags", "by_category", "by_severity",
              "by_protocol", "protocols_clean"):
        assert k in s
    for c in CATEGORIES:
        assert c in s["by_category"]
    for sev in SEVERITIES:
        assert sev in s["by_severity"]


def test_summary_protocols_clean_consistency(monitor):
    snap = monitor.export(offline=True, dry_run=True)
    flagged_protocols = {f["protocol"] for f in snap["red_flags"]}
    assert snap["summary"]["protocols_clean"] == \
        len([p for p in SPA_WHITELIST if p not in flagged_protocols])


# ─── D. Risk grade context ────────────────────────────────────────────────────


def test_load_risk_grades_from_scores_list(monitor, grades_a_to_d):
    monitor.risk_scores_file = grades_a_to_d
    g = monitor._load_risk_grades()
    assert g["aave-v3"] == "A"
    assert g["euler-v2"] == "D"


def test_load_risk_grades_from_protocols_dict(monitor, tmp_path):
    p = tmp_path / "rs2.json"
    p.write_text(json.dumps({
        "protocols": {
            "aave-v3":    {"grade": "a"},
            "morpho":     {"grade": "C"},
        }
    }))
    monitor.risk_scores_file = p
    g = monitor._load_risk_grades()
    assert g["aave-v3"] == "A"
    assert g["morpho"]  == "C"


def test_grade_is_poor_helper(monitor):
    assert monitor._grade_is_poor("C") is True
    assert monitor._grade_is_poor("D") is True
    assert monitor._grade_is_poor("F") is True
    assert monitor._grade_is_poor("A") is False
    assert monitor._grade_is_poor("B") is False
    assert monitor._grade_is_poor("") is False
    assert monitor._grade_is_poor(None) is False


# ─── E. Fallback paths ────────────────────────────────────────────────────────


def test_load_risk_grades_missing_file_returns_empty(monitor):
    # tmp_path file doesn't exist by default — empty dict.
    monitor.risk_scores_file = Path("/no/such/path/here.json")
    assert monitor._load_risk_grades() == {}


def test_load_risk_grades_garbage_file_returns_empty(monitor, tmp_path):
    p = tmp_path / "junk.json"
    p.write_text("not-json{{{")
    monitor.risk_scores_file = p
    assert monitor._load_risk_grades() == {}


def test_apy_spike_falls_back_when_historical_missing(monitor):
    # historical_apy_file doesn't exist → bootstrap.
    records, source, fb = monitor._fetch_apy_spikes(offline=False)
    assert fb is True
    assert source == "bootstrap"
    assert records == list(BOOTSTRAP_APY_SPIKES)


# ─── F. Network fetch hooks ───────────────────────────────────────────────────


def test_offline_does_not_call_urlopen(monitor):
    with patch("urllib.request.urlopen") as urlopen_mock:
        monitor.scan_all(offline=True)
        urlopen_mock.assert_not_called()


def test_http_get_text_returns_none_on_urlerror(monitor):
    with patch("urllib.request.urlopen",
               side_effect=urllib.error.URLError("boom")):
        out = monitor._http_get_text("http://example.invalid/x")
    assert out is None


def test_http_post_json_returns_none_on_urlerror(monitor):
    with patch("urllib.request.urlopen",
               side_effect=urllib.error.URLError("boom")):
        out = monitor._http_post_json("http://example.invalid/x", {"q": 1})
    assert out is None


def test_fetch_tvl_drops_falls_back_when_all_fail(monitor):
    with patch.object(RedFlagMonitor, "_http_get_text", return_value=None):
        records, source, fb = monitor._fetch_tvl_drops(offline=False)
    assert fb is True
    assert source == "bootstrap"
    assert records == list(BOOTSTRAP_TVL_DROPS)


def test_parse_defillama_tvl_handles_minimal_payload():
    doc = {
        "tvl": [
            {"date": 1_716_000_000, "totalLiquidityUSD": 1_000_000_000},
            {"date": 1_716_000_000 - 24 * 3600, "totalLiquidityUSD": 1_300_000_000},
            {"date": 1_716_000_000 - 7 * 24 * 3600, "totalLiquidityUSD": 1_500_000_000},
        ]
    }
    out = RedFlagMonitor._parse_defillama_tvl("aave-v3", doc)
    assert out is not None
    assert out["protocol"] == "aave-v3"
    # 1.0/1.3 → -23.08 %
    assert round(out["delta_24h"], 1) == -23.1
    # 1.0/1.5 → -33.33 %
    assert round(out["delta_7d"], 1) == -33.3


def test_parse_defillama_tvl_returns_none_on_garbage():
    assert RedFlagMonitor._parse_defillama_tvl("aave-v3", None) is None
    assert RedFlagMonitor._parse_defillama_tvl("aave-v3", {}) is None
    assert RedFlagMonitor._parse_defillama_tvl("aave-v3",
                                                {"tvl": []}) is None
    assert RedFlagMonitor._parse_defillama_tvl(
        "aave-v3",
        {"tvl": [{"date": 1, "totalLiquidityUSD": 0}]}) is None


def test_fetch_governance_falls_back_when_post_fails(monitor):
    with patch.object(RedFlagMonitor, "_http_post_json", return_value=None):
        records, source, fb = monitor._fetch_governance(offline=False)
    assert fb is True
    assert source == "bootstrap"
    assert records == list(BOOTSTRAP_GOVERNANCE_PROPOSALS)


def test_fetch_unlocks_falls_back_when_get_fails(monitor):
    with patch.object(RedFlagMonitor, "_http_get_text", return_value=None):
        records, source, fb = monitor._fetch_unlocks(offline=False)
    assert fb is True
    assert source == "bootstrap"
    assert records == list(BOOTSTRAP_TOKEN_UNLOCKS)


# ─── G. CLI + determinism ─────────────────────────────────────────────────────


def test_cli_offline_dry_run_returns_zero(tmp_path):
    out = tmp_path / "out.json"
    rs  = tmp_path / "rs.json"
    apy = tmp_path / "apy.json"
    rc = rfm._cli([
        "--offline", "--dry-run",
        "--output", str(out),
        "--risk-scores", str(rs),
        "--historical-apy", str(apy),
    ])
    assert rc == 0
    assert not out.exists()


def test_cli_offline_writes_file(tmp_path):
    out = tmp_path / "out.json"
    rs  = tmp_path / "rs.json"
    apy = tmp_path / "apy.json"
    rc = rfm._cli([
        "--offline",
        "--output", str(out),
        "--risk-scores", str(rs),
        "--historical-apy", str(apy),
    ])
    assert rc == 0
    assert out.exists()
    doc = json.loads(out.read_text())
    assert doc["fallback_used"] is True


def test_offline_export_is_deterministic_modulo_timestamps(tmp_path):
    out1 = tmp_path / "a.json"
    out2 = tmp_path / "b.json"
    m1 = RedFlagMonitor(output_file=out1,
                        risk_scores_file=tmp_path / "rs.json",
                        historical_apy_file=tmp_path / "apy.json")
    m2 = RedFlagMonitor(output_file=out2,
                        risk_scores_file=tmp_path / "rs.json",
                        historical_apy_file=tmp_path / "apy.json")
    s1 = m1.export(offline=True)
    s2 = m2.export(offline=True)
    # Strip volatile timestamps before comparison.
    def strip(snap):
        snap = json.loads(json.dumps(snap))
        snap.pop("generated_at", None)
        for f in snap["red_flags"]:
            f.pop("detected_at", None)
        return snap
    assert strip(s1) == strip(s2)


# ─── H. Module helpers + edge cases ───────────────────────────────────────────


def test_safe_float_handles_garbage():
    assert rfm._safe_float("3.14") == pytest.approx(3.14)
    assert rfm._safe_float(None) == 0.0
    assert rfm._safe_float("nope") == 0.0
    assert rfm._safe_float([], default=-1.0) == -1.0


def test_now_iso_ends_in_Z():
    out = rfm._now_iso()
    assert out.endswith("Z")
    # ISO format starts with year.
    assert out[:4].isdigit()


def test_closest_value_picks_nearest():
    series = [(100, 1.0), (200, 2.0), (300, 3.0)]
    assert rfm._closest_value(series, 205) == 2.0
    assert rfm._closest_value(series, 290) == 3.0
    assert rfm._closest_value(series, 0)   == 1.0
    assert rfm._closest_value([], 100)     == 0.0


def test_first_risk_tag_detects_keywords():
    assert rfm._first_risk_tag("Emergency pause for euler") == "emergency"
    assert rfm._first_risk_tag("Routine upgrade of comet")  == "upgrade"
    assert rfm._first_risk_tag("Treasury allocation vote")  == "treasury"
    assert rfm._first_risk_tag("Vote to mint NFT")          is None


def test_snapshot_space_to_slug():
    assert rfm._snapshot_space_to_slug("aave.eth")      == "aave-v3"
    assert rfm._snapshot_space_to_slug("comp-vote.eth") == "compound-v3"
    assert rfm._snapshot_space_to_slug("not-a-space")   == ""
    assert rfm._snapshot_space_to_slug("")              == ""


def test_defillama_unlock_to_slug():
    assert rfm._defillama_unlock_to_slug("Pendle")      == "pendle-pt"
    assert rfm._defillama_unlock_to_slug("Aave")        == "aave-v3"
    assert rfm._defillama_unlock_to_slug("Ethena")      == "ethena-susde"
    assert rfm._defillama_unlock_to_slug("UnknownProj") == ""
    assert rfm._defillama_unlock_to_slug("")            == ""


def test_series_key_to_slug_longest_prefix_wins():
    assert rfm._series_key_to_slug("aave-v3-usdc-ethereum") == "aave-v3"
    assert rfm._series_key_to_slug("pendle-pt-eth-mainnet") == "pendle-pt"
    # Unknown prefix yields empty string.
    assert rfm._series_key_to_slug("foo-bar")               == ""
    assert rfm._series_key_to_slug("")                      == ""


def test_dedupe_and_sort_keeps_critical_over_warn():
    f1 = RedFlag(protocol="aave-v3", category="tvl_drop", severity="WARN")
    f2 = RedFlag(protocol="aave-v3", category="tvl_drop", severity="CRITICAL")
    out = RedFlagMonitor._dedupe_and_sort([f1, f2])
    assert len(out) == 1
    assert out[0].severity == "CRITICAL"


def test_classify_ignores_non_whitelist_protocol(monitor):
    flags = monitor._classify_tvl_drops([{
        "protocol":    "fake-protocol",
        "delta_24h":   -50.0,
        "delta_7d":    -60.0,
        "tvl_now":     1.0,
        "tvl_24h_ago": 2.0,
        "tvl_7d_ago":  3.0,
    }], {})
    assert flags == []


def test_governance_skips_empty_tag(monitor):
    flags = monitor._classify_governance([
        {"protocol": "aave-v3", "tag": "", "title": "x", "deadline": "",
         "proposal_id": "0x", "space": "aave.eth"}
    ], {})
    assert flags == []


def test_scan_all_never_raises_when_everything_fails(monitor):
    """All scan helpers are patched to raise. scan_all must still return []."""
    def boom(*a, **k):
        raise RuntimeError("boom")
    with patch.object(RedFlagMonitor, "_fetch_tvl_drops",  side_effect=boom), \
         patch.object(RedFlagMonitor, "_fetch_apy_spikes", side_effect=boom), \
         patch.object(RedFlagMonitor, "_fetch_governance", side_effect=boom), \
         patch.object(RedFlagMonitor, "_fetch_unlocks",    side_effect=boom):
        flags = monitor.scan_all(offline=False)
    # Each scan falls back to its bootstrap fixtures — so flags > 0.
    assert isinstance(flags, list)
    assert monitor._fallback_used is True


def test_export_swallows_write_errors(tmp_path):
    # Point output at a directory path that cannot be opened for writing.
    bad = tmp_path / "does" / "not" / "exist"
    # Make the parent unwritable by passing an obviously bad path; the
    # monitor must still return a snapshot.
    monitor = RedFlagMonitor(
        output_file=bad,
        risk_scores_file=tmp_path / "rs.json",
        historical_apy_file=tmp_path / "apy.json",
    )
    # We expect the directory autocreation to actually succeed for this
    # path; flip read-only to actually force a write failure via patching.
    with patch.object(Path, "write_text", side_effect=OSError("nope")):
        snap = monitor.export(offline=True)
    assert isinstance(snap, dict)
    assert snap["summary"]["total_flags"] >= 1


def test_protocols_clean_zero_when_all_flagged(monitor):
    # Synthesise a flag for every whitelist member.
    flags = [
        RedFlag(protocol=p, category="tvl_drop", severity="WARN")
        for p in SPA_WHITELIST
    ]
    snap = monitor._build_snapshot(flags)
    assert snap["summary"]["protocols_clean"] == 0


def test_governance_risk_tags_contains_critical_subset():
    for tag in GOVERNANCE_CRITICAL_TAGS:
        assert tag in GOVERNANCE_RISK_TAGS


def test_thresholds_are_positive_numbers():
    assert TVL_DROP_24H_THRESHOLD_PCT > 0
    assert TVL_DROP_7D_THRESHOLD_PCT > 0
    assert TVL_DROP_CRITICAL_PCT > TVL_DROP_7D_THRESHOLD_PCT
    assert APY_SPIKE_MULTIPLIER > 1
    assert APY_SPIKE_CRITICAL_RATIO > APY_SPIKE_MULTIPLIER
    assert UNLOCK_HORIZON_DAYS >= 1
    assert UNLOCK_CRITICAL_PCT_SUPPLY > 0


def test_scan_all_with_grade_context_upgrades_to_critical(monitor, grades_a_to_d):
    monitor.risk_scores_file = grades_a_to_d
    flags = monitor.scan_all(offline=True)
    # In the bootstrap, maple TVL drop now picks up grade C → CRITICAL.
    maple_flags = [f for f in flags
                   if f.protocol == "maple" and f.category == "tvl_drop"]
    assert maple_flags, "Expected a maple tvl_drop flag from bootstrap"
    assert maple_flags[0].severity == "CRITICAL"


def test_evidence_grade_field_propagated(monitor, grades_a_to_d):
    monitor.risk_scores_file = grades_a_to_d
    flags = monitor.scan_all(offline=True)
    # Pick any flag for a graded protocol.
    aave = [f for f in flags if f.protocol == "aave-v3"]
    if aave:
        assert aave[0].evidence.get("grade") == "A"


def test_export_snapshot_top_level_keys(monitor):
    snap = monitor.export(offline=True, dry_run=True)
    for k in ("generated_at", "monitor_version", "sources",
              "fallback_used", "red_flags", "summary"):
        assert k in snap


def test_bootstrap_apy_spike_ratios_are_above_multiplier():
    for rec in BOOTSTRAP_APY_SPIKES:
        ratio = rec["current"] / rec["baseline"]
        assert ratio >= APY_SPIKE_MULTIPLIER


def test_red_flag_default_severity_is_warn():
    f = RedFlag(protocol="aave-v3", category="tvl_drop")
    assert f.severity == "WARN"
