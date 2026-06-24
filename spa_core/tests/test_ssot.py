# LLM_FORBIDDEN
"""Tests for spa_core.governance.ssot — the SSOT manifest + presentation guard.

Hermetic: filesystem-touching tests use a tmp data_dir; we never rely on the
live data/ contents for assertions (only for the optional real-file smoke).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.governance import ssot


# ─── fixtures ────────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_data(tmp_path: Path) -> Path:
    """A tmp data/ dir seeded with canonical shapes mirroring the real files."""
    (tmp_path / "paper_trading_status.json").write_text(
        json.dumps(
            {
                "days_running": 15,
                "paper_start_date": "2026-06-10",
                "current_equity": 100170.4,
                "total_return_pct": 0.1704,
                "apy_today_pct": 3.5994,
                "daily_yield_usd": 9.8772,
                "market_regime": "VOLATILE",
            }
        )
    )
    (tmp_path / "golive_status.json").write_text(
        json.dumps({"ready": False, "passed": 27, "total": 29})
    )
    (tmp_path / "tier1_nav_proof.json").write_text(
        json.dumps({"computed_nav_usd": 100170.4, "reconciliation_ok": True})
    )
    return tmp_path


# ─── registry / canonical_source ──────────────────────────────────────────────────


def test_registry_covers_core_types():
    reg = ssot.registry()
    for core in [
        "code",
        "strategy-configs",
        "risk-limits",
        "portfolio-state",
        "positions",
        "equity",
        "track",
        "golive-criteria",
        "backtest-results",
        "packages",
        "agent-health",
        "nav",
    ]:
        assert core in reg, f"missing data_type {core}"
        assert "canonical" in reg[core] and "kind" in reg[core]


def test_registry_is_a_copy_not_aliased():
    a = ssot.registry()
    a["nav"]["canonical"] = "MUTATED"
    b = ssot.registry()
    assert b["nav"]["canonical"] == "tier1_nav_proof.json"


def test_canonical_source_expected_paths():
    assert ssot.canonical_source("golive-criteria") == "golive_status.json"
    assert ssot.canonical_source("track") == "paper_trading_status.json"
    assert ssot.canonical_source("equity") == "equity_curve_daily.json"
    assert ssot.canonical_source("nav") == "tier1_nav_proof.json"
    assert ssot.canonical_source("packages") == "tier1_packages.json"
    assert ssot.canonical_source("agent-health") == "agent_health.json"
    # github kinds → repo identity string
    assert ssot.canonical_source("code") == ssot.GITHUB_REPO
    assert ssot.canonical_source("risk-limits") == ssot.GITHUB_REPO
    # multi-file types
    assert ssot.canonical_source("backtest-results") == [
        "tier1_verdict.json",
        "mass_tournament_results.json",
    ]
    assert ssot.canonical_source("portfolio-state") == [
        "current_positions.json",
        "paper_trading_status.json",
    ]


def test_canonical_source_unknown_raises():
    with pytest.raises(KeyError):
        ssot.canonical_source("nonexistent-type")


# ─── read_canonical ────────────────────────────────────────────────────────────


def test_read_canonical_file(fake_data):
    doc = ssot.read_canonical("golive-criteria", data_dir=fake_data)
    assert doc["passed"] == 27 and doc["total"] == 29


def test_read_canonical_files_multi(fake_data):
    # tier1_verdict + mass_tournament absent in fake_data → graceful {}
    doc = ssot.read_canonical("backtest-results", data_dir=fake_data)
    assert set(doc) == {"tier1_verdict.json", "mass_tournament_results.json"}
    assert doc["tier1_verdict.json"] == {}


def test_read_canonical_github_kind():
    doc = ssot.read_canonical("code")
    assert doc == {"canonical": ssot.GITHUB_REPO, "kind": "github"}


def test_read_canonical_missing_file_graceful(tmp_path):
    assert ssot.read_canonical("track", data_dir=tmp_path) == {}


# ─── key_facts ─────────────────────────────────────────────────────────────────


def test_key_facts_reads_from_files(fake_data):
    f = ssot.key_facts(data_dir=fake_data)
    assert f["track_days"] == 15
    assert f["apy_today_pct"] == 3.5994
    assert f["golive_passed"] == 27
    assert f["golive_total"] == 29
    assert f["nav"] == 100170.4
    assert f["regime"] == "VOLATILE"
    assert f["ssot_version"] == ssot.SSOT_VERSION


def test_key_facts_graceful_when_absent(tmp_path):
    f = ssot.key_facts(data_dir=tmp_path)
    assert f["track_days"] is None
    assert f["apy_today_pct"] is None
    assert f["golive_passed"] is None
    # still returns the structural keys
    assert "nav" in f and "regime" in f


# ─── validate_presentation (the Law-3 guard) ────────────────────────────────────


def test_validate_flags_stale_track_days(fake_data):
    # site claims 11 track days but canon is 15 → divergence
    res = ssot.validate_presentation({"track_days": 11}, data_dir=fake_data)
    assert res["ok"] is False
    fields = {d["field"] for d in res["divergences"]}
    assert "track_days" in fields
    div = next(d for d in res["divergences"] if d["field"] == "track_days")
    assert div["claimed"] == 11 and div["canonical"] == 15


def test_validate_passes_matching_claim(fake_data):
    res = ssot.validate_presentation(
        {"track_days": 15, "apy_pct": 3.5994, "golive_passed": 27},
        data_dir=fake_data,
    )
    assert res["ok"] is True
    assert res["divergences"] == []
    assert set(res["checked"]) == {"track_days", "apy_pct", "golive_passed"}


def test_validate_flags_multiple_divergences(fake_data):
    res = ssot.validate_presentation(
        {"track_days": 11, "apy_pct": 6.8, "golive_passed": 20},
        data_dir=fake_data,
    )
    assert res["ok"] is False
    assert len(res["divergences"]) == 3


def test_validate_apy_within_tolerance(fake_data):
    # 3.5994 vs 3.60 → within _TOL_ABS_PCT → OK
    res = ssot.validate_presentation({"apy_pct": 3.60}, data_dir=fake_data)
    assert res["ok"] is True


def test_validate_regime_string_mismatch(fake_data):
    res = ssot.validate_presentation({"regime": "CALM"}, data_dir=fake_data)
    assert res["ok"] is False
    assert res["divergences"][0]["canonical"] == "VOLATILE"


def test_validate_unverifiable_claim(fake_data):
    res = ssot.validate_presentation({"made_up_field": 42}, data_dir=fake_data)
    assert "made_up_field" in res["unverifiable"]
    # unverifiable does not by itself fail the guard
    assert res["ok"] is True


def test_validate_claim_unbacked_when_canon_absent(tmp_path):
    # canon files absent → asserting a value is itself a divergence
    res = ssot.validate_presentation({"track_days": 30}, data_dir=tmp_path)
    assert res["ok"] is False


def test_validate_empty_claims_is_ok(fake_data):
    res = ssot.validate_presentation({}, data_dir=fake_data)
    assert res["ok"] is True and res["divergences"] == []


# ─── determinism ────────────────────────────────────────────────────────────────


def test_registry_deterministic():
    assert ssot.registry() == ssot.registry()


def test_validate_deterministic(fake_data):
    claims = {"track_days": 11, "apy_pct": 6.8}
    a = ssot.validate_presentation(claims, data_dir=fake_data)
    b = ssot.validate_presentation(claims, data_dir=fake_data)
    assert a["divergences"] == b["divergences"] and a["ok"] == b["ok"]


# ─── build_report ──────────────────────────────────────────────────────────────


def test_build_report_no_write_structure(fake_data):
    m = ssot.build_report(write=False, data_dir=fake_data)
    assert m["model"] == "ssot_manifest"
    assert m["llm_forbidden"] is True
    assert m["ssot_version"] == ssot.SSOT_VERSION
    assert "registry" in m and "key_facts" in m
    assert m["key_facts"]["track_days"] == 15
    # no file written
    assert not (fake_data / "ssot_manifest.json").exists()


def test_build_report_writes_atomic(fake_data):
    ssot.build_report(write=True, data_dir=fake_data)
    out = fake_data / "ssot_manifest.json"
    assert out.exists()
    loaded = json.loads(out.read_text())
    assert loaded["model"] == "ssot_manifest"
    assert loaded["registry"]["nav"]["canonical"] == "tier1_nav_proof.json"
    assert loaded["key_facts"]["golive_passed"] == 27


def test_module_has_llm_forbidden_marker():
    src = Path(ssot.__file__).read_text()
    assert "# LLM_FORBIDDEN" in src
