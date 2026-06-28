"""
spa_core/tests/test_master_attribution.py — WS-4.5 hash-anchored MASTER attribution report.

Pins: the report is hash-anchored over its DATA body (clock-independent, deterministic); a third party
can verify the anchor; mutating any anchored section is DETECTED (tamper-evident); the advisory
invariant is asserted (a live-capable / go-live-entangled book is REFUSED). The go-live track is never
touched.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json

import pytest

from spa_core.strategy_lab import master_attribution as ma


def _seed_captured(tmp_path):
    """Seed a tmp data root with a captured FixedCarry + rwa_sleeve so the master report has books."""
    import datetime

    def day(i):
        return (datetime.date(2026, 6, 1) + datetime.timedelta(days=i)).isoformat()

    paper = tmp_path / "rates_desk" / "paper"
    paper.mkdir(parents=True)
    (paper / "rates_desk_fixed_carry_series.json").write_text(json.dumps(
        {"id": "rates_desk_fixed_carry",
         "series": [{"date": day(i), "equity_usd": 100000.0 + 30.0 * i} for i in range(4)]}))
    lab = tmp_path / "strategy_lab_paper"
    lab.mkdir(parents=True)
    (lab / "rwa_sleeve_series.json").write_text(json.dumps(
        {"id": "rwa_sleeve",
         "series": [{"date": day(i), "equity_usd": 100000.0 + 9.0 * i} for i in range(4)]}))
    # a promotion report so rwa_sleeve captures
    (tmp_path / "strategy_lab").mkdir(parents=True, exist_ok=True)


# ── PROPERTY: anchored, deterministic, clock-independent, verifiable ──────────────────────────
def test_report_is_anchored_and_verifies(tmp_path):
    _seed_captured(tmp_path)
    r = ma.build_master_report(data_dir=tmp_path, floor_apy_pct=3.4, write=False,
                               now_iso="2026-06-28T00:00:00+00:00")
    assert "proof_hash" in r and isinstance(r["proof_hash"], str) and len(r["proof_hash"]) == 64
    v = ma.verify_master_report(r)
    assert v["valid"] is True
    assert v["recomputed_hash"] == r["proof_hash"]


def test_anchor_is_clock_independent(tmp_path):
    """The anchor is a PURE function of the DATA — changing the wall-clock does NOT change the hash."""
    _seed_captured(tmp_path)
    r1 = ma.build_master_report(data_dir=tmp_path, floor_apy_pct=3.4, write=False,
                                now_iso="2026-06-28T00:00:00+00:00")
    r2 = ma.build_master_report(data_dir=tmp_path, floor_apy_pct=3.4, write=False,
                                now_iso="2099-01-01T00:00:00+00:00")
    assert r1["proof_hash"] == r2["proof_hash"]


def test_deterministic_same_data_same_hash(tmp_path):
    _seed_captured(tmp_path)
    r1 = ma.build_master_report(data_dir=tmp_path, floor_apy_pct=3.4, write=False,
                                now_iso="2026-06-28T00:00:00+00:00")
    r2 = ma.build_master_report(data_dir=tmp_path, floor_apy_pct=3.4, write=False,
                                now_iso="2026-06-28T00:00:00+00:00")
    assert r1["proof_hash"] == r2["proof_hash"]


# ── RED-TEAM: tampering with any anchored section is DETECTED ─────────────────────────────────
def test_tamper_in_section_detected(tmp_path):
    _seed_captured(tmp_path)
    r = ma.build_master_report(data_dir=tmp_path, floor_apy_pct=3.4, write=False,
                               now_iso="2026-06-28T00:00:00+00:00")
    # mutate an anchored headline field
    r["headline"]["refusal_100pct_on_toxic"] = False
    assert ma.verify_master_report(r)["valid"] is False


def test_tamper_in_combined_carry_detected(tmp_path):
    _seed_captured(tmp_path)
    r = ma.build_master_report(data_dir=tmp_path, floor_apy_pct=3.4, write=False,
                               now_iso="2026-06-28T00:00:00+00:00")
    # inflate the combined carry leg → anchor must break
    r["combined_attribution"]["combined_carry_leg_usd"] = 999999.0
    assert ma.verify_master_report(r)["valid"] is False


def test_no_proof_hash_is_invalid(tmp_path):
    _seed_captured(tmp_path)
    r = ma.build_master_report(data_dir=tmp_path, floor_apy_pct=3.4, write=False)
    r.pop("proof_hash")
    assert ma.verify_master_report(r)["valid"] is False


# ── PROPERTY: the advisory invariant is asserted ──────────────────────────────────────────────
def test_report_is_advisory(tmp_path):
    _seed_captured(tmp_path)
    r = ma.build_master_report(data_dir=tmp_path, floor_apy_pct=3.4, write=False)
    assert r["is_advisory"] is True
    assert r["research_only"] is True
    assert r["separate_from_golive_track"] is True


def test_advisory_guard_rejects_live_book():
    """A non-advisory captured section RAISES (the master report can never anchor a live book)."""
    with pytest.raises(ValueError):
        ma._assert_advisory({"is_advisory": False}, where="captured_sleeves")
    with pytest.raises(ValueError):
        ma._assert_advisory({"separate_from_golive_track": False}, where="combined_attribution")


def test_headline_rolls_up_sections(tmp_path):
    _seed_captured(tmp_path)
    r = ma.build_master_report(data_dir=tmp_path, floor_apy_pct=3.4, write=False)
    h = r["headline"]
    assert h["rwa_floor_apy_pct"] == 3.4
    assert "refusal_100pct_on_toxic" in h
    assert "combined_reconciles" in h
    assert "matrix_valid" in h
